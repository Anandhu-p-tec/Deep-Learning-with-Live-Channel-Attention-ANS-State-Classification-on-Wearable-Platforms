"""Quick diagnostic to find available serial ports and check for ESP32."""

import serial.tools.list_ports
import serial

print("=" * 60)
print("AVAILABLE SERIAL PORTS")
print("=" * 60)

ports = list(serial.tools.list_ports.comports())
if not ports:
    print("❌ NO SERIAL PORTS FOUND!")
else:
    for port in ports:
        print(f"✓ {port.device}")
        print(f"  Description: {port.description}")
        print(f"  HWID: {port.hwid}")
        print()

print("=" * 60)
print("TESTING ESP32 CONNECTION ON COM3")
print("=" * 60)

try:
    ser = serial.Serial("COM3", 115200, timeout=2)
    print("✅ COM3 opened successfully")
    print("📡 Waiting for data (5 seconds)...\n")
    
    for i in range(5):
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"  [{i+1}] {line}")
        else:
            print(f"  [{i+1}] (no data)")
    
    ser.close()
    print("\n✓ Connection test complete")
    
except serial.SerialException as e:
    print(f"❌ Failed to open COM3: {e}")
    print("\n💡 TRY: Plug in the ESP32 USB cable")

print("=" * 60)
