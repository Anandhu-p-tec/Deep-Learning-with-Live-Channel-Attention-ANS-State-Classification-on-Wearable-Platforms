import serial
import time

print("Testing COM3 for any byte activity...")
try:
    ser = serial.Serial('COM3', 115200, timeout=1)
    print(f'Connected to COM3 at 115200 baud')
    print("Waiting 5 seconds for any bytes...\n")
    start = time.time()
    bytes_read = 0
    
    while time.time() - start < 5:
        try:
            if ser.in_waiting > 0:
                raw = ser.read(ser.in_waiting)
                print(f"Received {len(raw)} bytes: {raw}")
                bytes_read += len(raw)
            time.sleep(0.1)
        except Exception as e:
            print(f"Error reading: {e}")
            break
    
    print(f'\nTotal bytes received: {bytes_read}')
    if bytes_read == 0:
        print("⚠️  No data from ESP32 - device may not be sending or powered off")
    ser.close()
except Exception as e:
    print(f'ERROR: {e}')
