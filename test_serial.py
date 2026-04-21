import serial
import time

print("Testing COM3 connection...")
try:
    ser = serial.Serial('COM3', 115200, timeout=2)
    print(f'Connected to COM3 at 115200 baud')
    start = time.time()
    lines_read = 0
    print("Waiting for data (5 seconds)...")
    while time.time() - start < 5:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f'> {line}')
                lines_read += 1
        except Exception as e:
            pass
    print(f'Finished: Read {lines_read} lines in 5 seconds')
    ser.close()
except Exception as e:
    print(f'ERROR: {e}')
