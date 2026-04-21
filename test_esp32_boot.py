import serial
import time

print("Testing COM3 for ESP32 startup messages...")
print("=" * 60)
print("If ESP32 is working, you should see boot messages like:")
print("  MAX30105 OK / FAIL")
print("  MPU6050 OK / FAIL")
print("  DHT11 OK")
print("  AD8232 OK")
print("  BOOT_OK")
print("=" * 60)
print()

try:
    ser = serial.Serial('COM3', 115200, timeout=1)
    print(f'Connected to COM3 at 115200 baud')
    print("Waiting 10 seconds for ESP32 data or boot messages...\n")
    
    start = time.time()
    lines_read = 0
    
    while time.time() - start < 10:
        try:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f'[{time.time()-start:.1f}s] {line}')
                    lines_read += 1
        except Exception as e:
            pass
    
    print(f'\n✅ Total lines received: {lines_read}')
    if lines_read == 0:
        print("❌ No data from ESP32")
        print("\nPossible issues:")
        print("  1. ESP32 may not be reading values (sensors not connected)")
        print("  2. Arduino code may not be running on the device")
        print("  3. Serial connection issue (TX/RX not connected properly)")
        print("  4. Wrong baud rate (but we're using 115200 which is correct)")
        print("\nSolution: Try pressing the RESET button on ESP32")
    else:
        print("\n✅ ESP32 is responding! Check sensor values above.")
    
    ser.close()
except Exception as e:
    print(f'ERROR: {e}')
