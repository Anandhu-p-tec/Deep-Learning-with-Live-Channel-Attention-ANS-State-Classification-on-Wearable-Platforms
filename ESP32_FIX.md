# 🔧 EMERGENCY ESP32 FIX GUIDE

## ❌ PROBLEM
ESP32 is **NOT responding** on COM3 - serial connection timeout

## ✅ IMMEDIATE FIX (DO THIS NOW!)

### Step 1: Physical Reset
```
⏸️  UNPLUG the USB cable from ESP32
   
⏱️  Wait 3 seconds
   
🔌 PLUG USB cable back in
   
⏳ Wait 5 seconds for ESP32 to boot
```

### Step 2: Verify Connection
Run this test:
```powershell
python test_serial_raw.py
```

**Expected output:**
```
✓ Connected to COM3 at 115200 baud
📡 Waiting for data (5 seconds)...
Received XXX bytes: ...
```

### Step 3: If Still Not Connecting

**Check Device Manager:**
- Click Start → Type "Device Manager"
- Look for "Silicon Labs CP210x USB to UART Bridge"
- Note which COM port it shows
- If not there: USB driver missing or cable issue

**Try Different USB Port:**
```powershell
$env:COM_PORT = "COM4"  # Try different port
python test_serial_raw.py
```

---

## 📤 UPLOAD FIRMWARE (Once Connected)

When ESP32 is responding, run:
```powershell
.\UPLOAD_FIRMWARE.ps1
```

This will:
1. ✓ Verify ESP32 is online
2. ✓ Erase flash memory completely
3. → Open Arduino IDE for final upload

---

## 🛑 IF NOTHING WORKS

1. **Check USB Cable**: Use a different USB cable (data cable, not just charging)
2. **Check Power**: ESP32 should have LED indicator light ON
3. **Drivers**: Download from https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
4. **Restart Computer**: Sometimes Windows serial drivers get stuck

---

## ✨ ONCE ESP32 IS WORKING

App will **auto-detect** and start streaming sensor data!
- GSR (Galvanic Skin Response)
- SPO2 (Blood Oxygen)
- ECG (Heart Rate)
- Temperature, Acceleration, etc.
