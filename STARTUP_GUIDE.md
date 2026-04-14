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

Expected output includes:

- `Starting ANS dashboard in demo-safe mode...`
- `Local URL: http://localhost:8511`

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

When connected and streaming, terminal should show logs like:

- `ESP32 CONNECTED on COM3`
- `[SERIAL] GSR=..., SPO2=..., TEMP=..., BPM=..., STATE=...`

If not streaming, check:

- USB cable and COM port
- firmware serial format includes keys: `GSR,SPO2,TEMP,AX,AY,AZ,BPM,RISK,STATE,ECG,ECG_HR,LO`

## 6) Stop the app

In the terminal where Streamlit is running:

- press `Ctrl+C`

---

## Optional: Manual start (without demo script)

Use venv directly:

```powershell
& .\.venv\Scripts\Activate.ps1
python -m streamlit run app.py --server.port 8511
```

If missing packages:

```powershell
python -m pip install streamlit pyserial
```

## Daily quick flow

```powershell
cd C:\Users\ranan\Desktop\Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms
.\run_demo.ps1
```

Then open http://localhost:8511
