import os
import time
import pyautogui
from PIL import Image, ImageFilter
import tkinter as tk
from tkinter import messagebox, IntVar
import threading
import sys
from pynput import mouse, keyboard
import numpy as np
import boto3
import msvcrt
from io import BytesIO
import queue
import socket

# Global configurations..........
activity_interval = 5  # in seconds
screenshot_interval = 5  # in minutes
capture_screenshots = True
capture_blurred = False
capturing = False
aws_bucket_name = 'adityasinghbucket'  # Replace with your actual bucket name
aws_region = 'us-east-1'  # Replace with your AWS region, e.g., 'us-west-2'
offline_queue = queue.Queue()  # Queue to store offline uploads

# AWS S3 client
s3_client = boto3.client('s3', region_name=aws_region)

# Activity tracking variables
mouse_positions = []
key_presses = []
last_activity_time = time.time()

# Function to upload files with retry on failure
def upload_to_s3(filename, data, is_log=False):
    key = f"logs/{filename}" if is_log else f"screenshots/{filename}"
    try:
        if is_log:
            # Log is plain text
            s3_client.put_object(Body=data.getvalue(), Bucket=aws_bucket_name, Key=key)
        else:
            # Screenshot is binary data
            s3_client.upload_fileobj(data, aws_bucket_name, key)
        print(f"Uploaded {key} successfully.")
    except Exception as e:
        print(f"Error uploading {key}: {e}")
        # Enqueue for later retry
        offline_queue.put((filename, data, is_log))

# Function to process queued uploads (retry)
def process_offline_queue():
    while not offline_queue.empty():
        filename, data, is_log = offline_queue.get()
        try:
            upload_to_s3(filename, data, is_log)
        except Exception as e:
            print(f"Retry failed for {filename}: {e}")
            offline_queue.put((filename, data, is_log))
            break  # Stop further processing if network is still down

# Function to check internet connection
def is_connected():
    try:
        # Try to connect to a public DNS server (Google DNS)
        socket.create_connection(("8.8.8.8", 53))
        return True
    except OSError:
        return False

# Function to capture and upload screenshot
def capture_and_upload_screenshot():
    if not capture_screenshots:
        return
    screenshot = pyautogui.screenshot()
    if capture_blurred:
        screenshot = screenshot.filter(ImageFilter.GaussianBlur(10))
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f'screenshot_{timestamp}.png'

    # Save to BytesIO object instead of file
    img_byte_arr = BytesIO()
    screenshot.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    if is_connected():
        upload_to_s3(filename, img_byte_arr, is_log=False)
    else:
        print("No internet connection. Screenshot added to the queue.")
        offline_queue.put((filename, img_byte_arr, False))

# Function to log activity
def log_activity():
    global mouse_positions, key_presses, last_activity_time
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f'activity_log_{timestamp}.txt'
    log_content = f"Mouse movements: {mouse_positions}\nKey presses: {key_presses}\n"

    log_data = BytesIO(log_content.encode())
    log_data.seek(0)

    if is_connected():
        upload_to_s3(filename, log_data, is_log=True)
    else:
        print("No internet connection. Log added to the queue.")
        offline_queue.put((filename, log_data, True))

    mouse_positions = []
    key_presses = []
    last_activity_time = time.time()

# Function to detect irregular activity
def is_irregular_activity():
    if len(mouse_positions) < 2:
        return False
    
    
    diffs = np.diff(mouse_positions, axis=0)
    if np.all(diffs == diffs[0]):  
        return True
    
    # Check for unnaturally fast keyboard input
    if len(key_presses) > 20:
        avg_time_between_presses = np.mean(np.diff(key_presses))
        if avg_time_between_presses < 0.05:  # Less than 50ms between keypresses on average
            return True
    
    return False

# Mouse listener callback
def on_move(x, y):
    global mouse_positions
    mouse_positions.append((x, y))

# Keyboard listener callback
def on_press(key):
    global key_presses
    key_presses.append(time.time())

# Function to continuously monitor activity
def activity_monitoring_task():
    global capturing
    mouse_listener = mouse.Listener(on_move=on_move)
    keyboard_listener = keyboard.Listener(on_press=on_press)
    mouse_listener.start()
    keyboard_listener.start()

    while capturing:
        time.sleep(activity_interval)
        if time.time() - last_activity_time >= activity_interval:
            if not is_irregular_activity():
                log_activity()
            else:
                print("Irregular activity detected. Discarding this interval.")
        process_offline_queue()  # Retry uploading from the queue if possible

    mouse_listener.stop()
    keyboard_listener.stop()

# Function to capture screenshots at intervals
def screenshot_task():
    global capturing
    while capturing:
        capture_and_upload_screenshot()
        process_offline_queue()  # Retry uploading from the queue if possible
        time.sleep(screenshot_interval * 60)

# Start capturing
def start_capturing():
    global capturing
    if not capturing:
        capturing = True
        threading.Thread(target=activity_monitoring_task, daemon=True).start()
        if capture_screenshots:
            threading.Thread(target=screenshot_task, daemon=True).start()
        messagebox.showinfo("Status", "Activity tracking started.")

# Stop capturing
def stop_capturing():
    global capturing
    capturing = False
    messagebox.showinfo("Status", "Activity tracking stopped.")

# Set activity interval
def set_activity_interval(value):
    global activity_interval
    activity_interval = int(value)
    print(f"Activity logging interval set to: {activity_interval} seconds")

# Set screenshot interval
def set_screenshot_interval(value):
    global screenshot_interval
    screenshot_interval = int(value)
    print(f"Screenshot interval set to: {screenshot_interval} minutes")

# Toggle screenshot capture
def toggle_screenshot_capture():
    global capture_screenshots
    capture_screenshots = not capture_screenshots
    state = "Enabled" if capture_screenshots else "Disabled"
    print(f"Screenshot capture: {state}")

# Toggle screenshot blur
def toggle_blur():
    global capture_blurred
    capture_blurred = not capture_blurred
    state = "Blurred" if capture_blurred else "Clear"
    print(f"Screenshots will be: {state}")

def check_single_instance():
    lock_file = 'my_app.lock'
    global lock_file_obj
    lock_file_obj = open(lock_file, 'w')
    try:
        msvcrt.locking(lock_file_obj.fileno(), msvcrt.LK_NBLCK, 1)
    except IOError:
        messagebox.showerror("Error", "Another instance of the application is already running.")
        sys.exit()

# Check for single instance
check_single_instance()

# GUI setup
root = tk.Tk()
root.title("Activity Tracking Agent")

# Start/Stop buttons
start_button = tk.Button(root, text="Start Tracking", command=start_capturing)
start_button.grid(row=0, column=0, padx=10, pady=10)
stop_button = tk.Button(root, text="Stop Tracking", command=stop_capturing)
stop_button.grid(row=0, column=1, padx=10, pady=10)

# Activity interval setting
activity_label = tk.Label(root, text="Activity Logging Interval (seconds):")
activity_label.grid(row=1, column=0, padx=10, pady=10)
activity_slider = tk.Scale(root, from_=1, to=60, orient='horizontal', command=set_activity_interval)
activity_slider.set(activity_interval)
activity_slider.grid(row=1, column=1, padx=10, pady=10)

# Screenshot interval setting
screenshot_label = tk.Label(root, text="Screenshot Interval (minutes):")
screenshot_label.grid(row=2, column=0, padx=10, pady=10)
screenshot_slider = tk.Scale(root, from_=1, to=60, orient='horizontal', command=set_screenshot_interval)
screenshot_slider.set(screenshot_interval)
screenshot_slider.grid(row=2, column=1, padx=10, pady=10)

# Screenshot capture toggle
screenshot_var = IntVar()
screenshot_check = tk.Checkbutton(root, text="Capture Screenshots", variable=screenshot_var, command=toggle_screenshot_capture)
screenshot_check.select()
screenshot_check.grid(row=3, column=0, padx=10, pady=10)

# Blur option checkbox
blur_var = IntVar()
blur_check = tk.Checkbutton(root, text="Blur Screenshots", variable=blur_var, command=toggle_blur)
blur_check.grid(row=3, column=1, padx=10, pady=10)

# Run the Tkinter main loop
root.mainloop()
