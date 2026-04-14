# Startup Guide (Windows)

This guide is for the current project setup and demo flow.

## 1) Open project

Open PowerShell in:

`C:\Users\ranan\Desktop\Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms`

## 2) Start the app (recommended)

Use the demo launcher:

```powershell
.\run_demo.ps1
```

**⏱️ First startup may take 45+ seconds** as the app waits for hardware detection. This gives the ESP32 time to be recognized on the USB port.

Expected output includes:

- `Starting ANS dashboard in demo-safe mode...`
- `Local URL: http://localhost:8511`
- `[INIT] Background serial thread initialized`
- Within 45 seconds: **✅ ESP32 CONNECTED** (if hardware present) OR **⚠️ No hardware** (if not connected)

Open:

- http://localhost:8511

## 3) If port is busy

Run this, then start again:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8511 -State Listen -ErrorAction SilentlyContinue
if ($conn) { $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force } }
.\run_demo.ps1
```

## 4) If page goes blank / stale

1. Keep only one tab open for `localhost:8511`.
2. Press `Ctrl+F5` (hard refresh).
3. Close old `localhost:8501` tabs.
4. Restart app with Step 3 command above.

## 5) ESP32 check

**When connected and streaming:**

Terminal should show:

```
✅ ESP32 CONNECTED on COM3 — Live mode active
[INIT] Background serial thread initialized
```

Dashboard shows: **● ESP32 Live**

**If NOT streaming:**

Terminal shows:

```
⚠️  No hardware — Simulation mode active
[SERIAL THREAD] Port error: FileNotFoundError ('COM3')
[SERIAL THREAD] Port error... (retrying every 2 seconds)
```

Dashboard shows: **◎ Simulation Mode** (automatically generates test data)

**To fix:**

- Check USB cable connection to ESP32
- Verify COM port: `Get-PnpDevice -Class Ports` (PowerShell)
- If different port, update in `.env`: `ESP32_PORT=COM5` (or your port)
- Restart app: `Ctrl+C`, then `.\ run_demo.ps1`
- Verify firmware includes: `GSR,SPO2,TEMP,AX,AY,AZ,BPM,RISK,STATE,ECG,ECG_HR,LO`

## 6) Stop the app

In the terminal where Streamlit is running:

- press `Ctrl+C`

---

## Optional: Manual start (without demo script)

Use venv_short directly:

```powershell
& .\.venv_short\Scripts\Activate.ps1
python -m streamlit run app.py --server.port 8511
```

If missing packages:

```powershell
.\venv_short\Scripts\python.exe -m pip install streamlit pyserial
```

## Daily quick flow

```powershell
cd C:\Users\ranan\Desktop\Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms
.\run_demo.ps1
```

Then open http://localhost:8511
