# ANS State Classification - Live Dashboard

## Quick Start (Windows)

```powershell
cd C:\Users\ranan\Desktop\Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms
.\run_demo.ps1
```

Then open http://localhost:8511

## Setup (One-time only)

### 1) Create environment

```powershell
python -m venv venv_short
.\venv_short\Scripts\python.exe -m pip install numpy tensorflow streamlit pyserial shap pandas plotly scipy groq python-dotenv scikit-learn --only-binary :all:
```

### 2) Environment variables

Ensure `.env` file exists in project root with:

```
GROQ_API_KEY=your_api_key_here
ESP32_PORT=COM3  # Adjust COM port as needed
```

## Hardware

- **Connected**: USB ESP32 streams live sensor data → Dashboard shows **● ESP32 Live**
- **Disconnected**: Dashboard enters simulation mode → Shows **◎ Simulation Mode**
- **Auto-detection**: App detects ESP32 on startup; reconnects automatically if unplugged

## Expected Terminal Output

### On startup:

```
Starting ANS dashboard in demo-safe mode...
[INIT] Background serial thread initialized
```

### With ESP32 connected:

```
✅ ESP32 CONNECTED on COM3 — Live mode active
[SERIAL THREAD] Port connected on COM3
```

### Without ESP32:

```
⚠️  No hardware — Simulation mode active
[SERIAL THREAD] Port error... (retrying every 2 seconds)
```