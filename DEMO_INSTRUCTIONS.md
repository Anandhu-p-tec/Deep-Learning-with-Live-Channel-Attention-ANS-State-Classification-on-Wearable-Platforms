# ANS State Classification Dashboard - Comprehensive Setup & Demo Guide

## 📋 Overview

This is a production-ready Streamlit dashboard for **real-time ANS (Autonomic Nervous System) state classification** from wearable sensor data using deep learning with channel attention and MC-dropout uncertainty.

### ANS States Monitored:
- 🟢 **Normal Baseline** — Relaxed, balanced ANS state
- 🔴 **Sympathetic Arousal** — High stress, alert state (fight-or-flight)
- 🔵 **Parasympathetic Suppression** — Under-activation, suppressed recovery
- 🟣 **Mixed Dysregulation** — Conflicting signals between branches

### Key Technology:
- **Model:** 1D-CNN + Channel Attention Vector (CAV) + BiLSTM + MC-Dropout
- **Sensors:** GSR (skin conductance), SpO2 (oxygen), Temperature, Accelerometer
- **Inference:** 500-sample time windows at ~1kHz sampling
- **Uncertainty:** Monte Carlo dropout creates confidence intervals

---

## 🚀 Quick Start (5 minutes)

### Demo-safe launch command

Use the short-path launcher during the presentation:

```powershell
.\run_demo.ps1
```

This uses the known-good `venv_short` environment and avoids the Windows long-path TensorFlow install issue.

### Step 1: Activate Virtual Environment

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**macOS/Linux:**
```bash
source venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

If you encounter TensorFlow installation errors on Windows with long paths, see **Troubleshooting** section below.

For the live demo, prefer `run_demo.ps1` instead of reinstalling dependencies.

### Step 3: Run the Dashboard
```bash
streamlit run app.py
```

The app will:
✅ Auto-detect ESP32 hardware (or run in simulation mode)  
✅ Load/create the AI model (first run takes ~30 seconds)  
✅ Open dashboard at **http://localhost:8501**

---

## 🔧 Installation Details

### Requirements
- Python 3.10 or higher
- ~2GB free disk space (for TensorFlow)
- 4GB+ RAM recommended

### Full Setup Process

```bash
# 1. Navigate to project
cd Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms

# 2. Activate venv
venv\Scripts\activate  # Windows
# OR
source venv/bin/activate  # macOS/Linux

# 3. Upgrade pip (recommended)
pip install --upgrade pip

# 4. Install all dependencies
pip install -r requirements.txt

# 5. (Optional) Pre-train the model for better performance
python model/train_model.py
```

### What Gets Installed:
- **streamlit** — Web dashboard framework
- **tensorflow** — Deep learning engine
- **numpy, scipy** — Numerical computing
- **pandas** — Data handling
- **plotly** — Interactive visualizations
- **scikit-learn** — ML utilities
- **pyserial** — ESP32 hardware communication
- **shap** — Model explainability

---

## 📊 Using the Dashboard

### Main Page: Live ANS Monitor

The dashboard displays in real-time:

#### 1. **Metrics Row** (top)
- 🎯 **Predicted ANS State** — Color-coded (see legend below)
- 📈 **Confidence** — How certain is the prediction (0-100%)
- 📊 **PCS Score** — Sensor coherence check (0-1)
- ⚠️ **Uncertainty** — MC-Dropout variance (higher = less certain)

#### 2. **Channel Attribution** (PAST Section)
Shows which sensors contributed most to the prediction:
- **GSR (Galvanic Skin Response):** Skin conductance
- **SpO2 (Blood Oxygen):** Oxygen saturation
- **Temperature:** Core body temp
- **Acceleration:** Movement/vibration

Each sensor gets a normalized weight (0-1, sum=1.0).

#### 3. **Classification History**
Interactive chart showing last 20 readings:
- X-axis: Reading number (over time)
- Y-axis: Confidence %
- Points colored by predicted ANS state
- Trend line for confidence evolution

#### 4. **Sidebar Controls**
- **Mode:** Auto-detect ESP32 or manual simulation  
- **Simulation State:** Choose from 4 physiological states (simulation mode only)
- **Reading Interval:** 1-10 seconds between readings (default 3s)
- **MC Passes:** 5-20 stochastic forward passes for uncertainty (default 10)
- **Export:** Download last prediction as JSON

#### 5. **Alert Panel** (bottom sidebar)
- 🟢 GREEN: All systems normal
- 🟠 ORANGE: Sensor misalignment detected
- 🟡 YELLOW: Low confidence prediction  
- 🔴 RED: High-confidence stress/arousal detected

---

## ⚙️ Configuration

### Sidebar Parameters

| Parameter | Range | Default | Use Case |
|-----------|-------|---------|----------|
| **Reading Interval** | 1-10 sec | 3 sec | Slower = more stable, Faster = more responsive |
| **MC Passes** | 5-20 | 10 | Higher = more robust uncertainty, slower inference |
| **Simulation State** | 4 modes | normal | Choose stressed, suppressed, mixed, or baseline |

### Mode Selection

**Auto Mode (Default):**
- Scans COM ports for ESP32 at startup
- If found: Uses live hardware data
- If not found: Falls back to simulation mode

**Manual Simulation:**
- Force simulation mode even if hardware connected
- Choose specific ANS state to simulate
- Useful for testing/demos

---

## 🔌 Hardware Integration (ESP32)

### Wiring Checklist

```
ESP32 Pin Configuration:
├── GPIO 34 (ADC1_CH6) ← GSR sensor (0-3.3V ADC range)
├── GPIO 35 (ADC1_CH7) ← SpO2 sensor (optional I2C alternate)
├── GPIO 36 (ADC1_CH0) ← Temperature sensor (or I2C)
├── I2C SDA (GPIO 21)  ← Accelerometer (MPU6050/LSM6DS3)
├── I2C SCL (GPIO 22)  ← Accelerometer
└── GND & 3.3V        ← Power distribution
```

### Serial Communication Format

ESP32 must send one line per second at **115200 baud**:

```
GSR:512,SPO2:98.2,TEMP:36.5,AX:0.1,AY:0.02,AZ:9.8
```

Mapping:
- **GSR:** 0-1023 ADC value
- **SPO2:** 90-100 % oxygen saturation
- **TEMP:** 35-40 °C body temperature
- **AX, AY, AZ:** ±2g accelerometer values

### Connection Troubleshooting

```bash
# Check if ESP32 is recognized
# Windows:
Get-WmiObject Win32_SerialPort

# macOS:
ls /dev/tty.usbserial*

# Linux:
ls /dev/ttyUSB*
dmesg | grep ttyUSB  # to see connection messages
```

---

## 🎮 Simulation Mode

### 4 Built-In Physiological States

**1. Normal Baseline**
- GSR: ~400 (relaxed skin conductance)
- SpO2: ~98% (normal saturation)
- Temp: ~36.5°C (normal body temp)
- Accel: ~0g (minimal movement)

**2. Sympathetic Arousal** (Stress/Alert)
- GSR: ~750 (elevated - sweating)
- SpO2: ~96% (slight decrease)
- Temp: ~37.2°C (increased)
- Accel: ~0.2g (fidgeting/shaking)

**3. Parasympathetic Suppression** (Under-activation)
- GSR: ~300 (low - relaxed)
- SpO2: ~93% (suppressed)
- Temp: ~36.0°C (slightly low)
- Accel: ~0g (minimal movement)

**4. Mixed Dysregulation** (Conflicting Signals)
- GSR: ~650 (elevated)
- SpO2: ~94% (moderate)
- Temp: ~37.5°C (elevated)
- Accel: ~0.3g (moderate movement)

All values include **Gaussian noise (2% of range)** for realistic variation.

---

## 🧠 Model Architecture Deep Dive

```
Input: (500 samples, 4 sensors) normalized to [0, 1]
  ↓
[FEATURE EXTRACTION]
Conv1D(32 filters, kernel=5) + BatchNorm + MaxPool(2)
  Output shape: (250, 32)
  ↓
Conv1D(64 filters, kernel=3) + BatchNorm + MaxPool(2)
  Output shape: (125, 64)
  ↓
[CHANNEL ATTENTION MECHANISM]
GlobalAveragePooling1D → (64,)
  ↓
Dense(4) + Softmax → Channel Attention Vector (CAV)
  CAV shape: (4,) — weights for [GSR, SpO2, Temp, Accel]
  ↓
[WEIGHTED SENSOR PROCESSING]
Apply CAV weights to input channels
Bidirectional LSTM(32) → (64,) bidirectional hidden
    Total: 128-dim representation
  ↓
[MC-DROPOUT UNCERTAINTY]
Dropout(0.4) — kept ACTIVE during inference for stochasticity
  ↓
[CLASSIFICATION]
Dense(32, ReLU)
  ↓
Dense(4, Softmax) → Final class probabilities
```

### Model Capabilities

| Capability | Implementation | Purpose |
|------------|------------------|---------|
| **Channel Attention** | CAV weights per sensor | Interpretability: which sensors matter |
| **Temporal Processing** | 1D-CNN + BiLSTM | Capture time series patterns |
| **Uncertainty** | MC-Dropout T=20 | Confidence intervals on predictions |
| **Per-Channel Similarity** | Cosine similarity (PCS) | Detect sensor conflicts |

---

## 📈 Performance Metrics Explained

### Confidence
- **Definition:** Maximum class probability (0-100%)
- **Good:** > 75% (reliable prediction)
- **Warning:** 50-75% (uncertain)
- **Alert:** < 50% (unreliable)

### Variance / Uncertainty
- **Definition:** Statistical variance across 20 MC-Dropout forward passes
- **Values:** 0-1 (higher = more uncertain)
- **Threshold:** > 0.12 triggers "Low Confidence" flag

### PCS (Per-Channel Similarity)
- **Definition:** Cosine similarity between top-2 dominant channel representations
- **Range:** 0-1 (1 = perfect agreement)
- **Threshold:** < 0.30 triggers "Sensor Conflict" alert

### CAV (Channel Attention Vector)
- **Definition:** Learned weights for each sensor
- **Sum:** Always = 1.0 (normalized)
- **Interpretation:** Higher weight = more influential to prediction

---

## 🚨 Alert System

### Alert Types & Triggers

| Alert | Color | Condition | Action |
|-------|-------|-----------|--------|
| **Sympathetic Arousal** | 🔴 RED | Class + Confidence > 75% | Check stress source |
| **Parasympathetic Suppression** | 🔵 BLUE | Class + Confidence > 75% | Check for depression/fatigue |
| **Low Confidence** | 🟡 YELLOW | Variance > 0.12 | Unreliable prediction |
| **Sensor Conflict** | 🟠 ORANGE | PCS < 0.30 | Check sensor contact/calibration |
| **All Clear** | 🟢 GREEN | None of above | Normal operation |

---

## 🛠️ Troubleshooting

### Issue: TensorFlow Installation Fails (Windows)

**Cause:** Windows long-path limitation (path > 260 characters)

**Solution 1: Enable Long Path Support (Windows 10+)**
```powershell
# Run as Administrator:
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType dword -Force

# Then retry pip install
pip install tensorflow
```

**Solution 2: Move Project to Shorter Path**
```bash
# Move from:
C:\Users\ranan\Desktop\Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms

# To:
C:\Projects\ans_project
```

**Solution 3: Use WSL2 (Linux Environment)**
```bash
wsl --install
# Continue setup inside WSL2 Ubuntu
```

### Issue: "ModuleNotFoundError: No module named 'tensorflow.python'"

**Solution:**
```bash
# Reinstall TensorFlow fresh
pip uninstall tensorflow -y
pip cache purge
pip install --no-cache-dir tensorflow
```

### Issue: ESP32 Not Detected

**Checklist:**
1. Check USB cable connection
2. Install CH340 drivers (common for ESP32 dev boards)
3. Verify COM port in Device Manager (Windows) or `ls /dev` (macOS/Linux)
4. Test serial communication:
   ```bash
   python -c "import serial; print(serial.tools.list_ports.comports())"
   ```

### Issue: App Crashes or Hangs

```bash
# Full restart:
pkill streamlit  # Kill any running streamlit
.\venv\Scripts\activate
streamlit cache clear
streamlit run app.py
```

### Issue: Model Training Out of Memory

Edit `model/train_model.py`:
```python
# Reduce batch size
batch_size=16  # From 32

# or reduce epochs
epochs=3  # From 5

# or reduce windows per class
windows_per_class=200  # From 310
```

---

## 📁 Project Structure

```
Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms/
├── 📄 app.py                           # Main Streamlit dashboard (run this!)
├── 📄 requirements.txt                 # All Python dependencies
├── 📄 README.md                        # Project overview
├── 📄 .gitignore                       # Git ignore rules
│
├── 📁 venv/                           # Python virtual environment (auto-created)
│
├── 📁 model/                          # AI Model code
│   ├── 📄 model_utils.py              # ANSClassifier + utilities
│   ├── 📄 train_model.py              # Training script (generates ans_model.h5)
│   └── 📁 saved/
│       ├── 📄 ans_model.h5            # Trained model weights (after first run)
│       └── 📄 .gitkeep                # (ensures folder exists in git)
│
├── 📁 serial_reader/                  # Hardware/Simulation
│   ├── 📄 simulator.py                # Synthetic sensor data (4 modes)
│   ├── 📄 esp32_reader.py             # ESP32 serial interface
│   └── 📄 __init__.py                 # (optional Python package marker)
│
└── 📄 DEMO_INSTRUCTIONS.md            # This file
```

---

## 📊 Data Specifications

### Input Format (Normalized to [0, 1])

| Sensor | Raw Range | Normalized | Sampling |
|--------|-----------|------------|----------|
| GSR | 0-1023 ADC | 0-1 | ~1kHz |
| SpO2 | 90-100 % | 0-1 | ~1kHz |
| Temperature | 35-40 °C | 0-1 | ~1kHz |
| Accel Magnitude | 0-20 m/s² | 0-1 | ~1kHz |

### Prediction Output JSON

```json
{
  "predicted_class": "Normal Baseline",
  "confidence": 87.3,
  "variance": 0.0234,
  "low_confidence": false,
  "cav": {
    "GSR": 0.35,
    "SpO2": 0.25,
    "Temp": 0.20,
    "Accel": 0.20
  },
  "dominant_sensor": "GSR",
  "all_probs": {
    "Normal Baseline": 0.873,
    "Sympathetic Arousal": 0.087,
    "Parasympathetic Suppression": 0.030,
    "Mixed Dysregulation": 0.010
  }
}
```

---

## 🔬 Advanced Usage

### Custom Training Data

To train on real sensor recordings:

1. Collect data as CSV: `gsr,spo2,temp,ax,ay,az` (500 rows per window)
2. Create Python script:
   ```python
   import numpy as np
   from model.model_utils import build_model
   
   # Load your data
   X = np.load('your_data.npy')  # Shape: (N, 500, 4)
   y = np.load('your_labels.npy')  # Shape: (N,)
   
   # Build and train
   model = build_model()
   model.fit(X, y, epochs=10, batch_size=32)
   model.save('model/saved/ans_model.h5')
   ```

### Fine-tuning Pre-trained Model

```python
from model.model_utils import load_or_create_model

model = load_or_create_model()
# Model is already trained.
# To fine-tune on new data:
model.fit(new_X, new_y, epochs=2, batch_size=16)
```

---

## 📚 References & Resources

### Documentation
- TensorFlow/Keras: https://keras.io
- Streamlit: https://docs.streamlit.io
- PySerial: https://pyserial.readthedocs.io

### Papers & Theory
- MC-Dropout Uncertainty: https://arxiv.org/abs/1506.02142
- Channel Attention: https://arxiv.org/abs/1809.03713
- 1D-CNN Time Series: https://arxiv.org/abs/1611.06102

### Hardware
- ESP32 MicroPython: https://micropython.org
- CH340 Drivers: https://sparks.gogo.co.nz/ch340.html
- MPU6050 Accelerometer: https://invensense.tdk.com

---

## 🎯 Next Steps

1. ✅ Install dependencies & run `streamlit run app.py`
2. ✅ Try simulation mode with all 4 ANS states
3. ✅ Optional: Connect ESP32 hardware
4. ✅ Optional: Retrain model with `python model/train_model.py`
5. ✅ Optional: Export predictions and analyze trends

---

**Status:** Production-Ready  
**Last Updated:** April 2026  
**Support:** Check troubleshooting section or review terminal output for error details

**Expected output:**
```
Generating synthetic dataset (1240 windows)...
Dataset shape: X=(1240, 500, 4), y=(1240, 4)
Training model for 5 epochs...
Epoch 1/5 ... 
Final accuracy: 98.5%
Model saved to: model/saved/ans_model.h5
```

The trained model is saved to `model/saved/ans_model.h5`.

## Running the Dashboard

### Start the Streamlit App
```bash
streamlit run app.py
```

**Expected output:**
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.x.x:8501
```

Open your browser to `http://localhost:8501` to see the live dashboard.

## Dashboard Features

### 📊 Live Monitor (Default Page)
- **Connection Status Badge** — Shows "ESP32 Connected" (green) or "Simulation Mode" (yellow)
- **Simulation Mode Selector** — Only visible when no hardware detected. Choose from:
  - Normal Baseline
  - Sympathetic Arousal
  - Parasympathetic Suppression
  - Mixed Dysregulation

### ❤️ Main Metrics
1. **ANS State** — Predicted classification (colored using CLASS_COLORS)
2. **Confidence** — Prediction probability (0-100%)
3. **PCS Score** — Per-channel similarity (0-1). Shows "✓ Coherent" or "⚠ Sensor Conflict"
4. **Uncertainty** — MC-Dropout variance. Warns if variance > 0.12

### 🎯 Sensor Contribution (PAST)
- **Progress Bars** — Shows weight of each sensor (GSR, SpO2, Temp, Accel)
- **Horizontal Bar Chart** — Visual representation of channel attention weights
- Dominant sensor is marked with bold and arrow

### 📈 Classification History
- **Confidence Trend** — Line chart showing confidence % over last 20 readings
- **Color-coded by ANS State** — Each class has its own color from CLASS_COLORS

### ⚙️ Sidebar Controls
- **Reading Interval** (1-10 seconds) — How often to acquire new data
- **MC Dropout Passes** (5-20 passes) — Uncertainty estimation granularity
- **Export Last Reading** — Download latest prediction as JSON

### 🚨 Alerts Panel
The app shows system alerts in the sidebar:
- ⚠️ **LOW CONFIDENCE** — Prediction unreliable (variance > 0.12)
- ⚠️ **SENSOR CONFLICT** — Sensor disagreement (PCS < 0.30)
- 🔴 **ALERT — Sympathetic Arousal** — High stress detected (confidence > 75%)
- 🔵 **ALERT — Parasympathetic Suppression** — Suppressed state detected (confidence > 75%)
- ✓ **No alerts** — All systems nominal

## Using Real Hardware (ESP32)

### ESP32 Serial Protocol
The app expects one line per second in this format:
```
GSR:512,SPO2:98.2,TEMP:36.5,AX:0.1,AY:0.02,AZ:9.8\n
```

**Fields:**
- **GSR** — Galvanic Skin Response (0-1023 ADC)
- **SPO2** — Blood Oxygen Saturation (90-100 %)
- **TEMP** — Body Temperature (35-40 °C)
- **AX, AY, AZ** — 3-axis Acceleration (-2 to +2 g)

### ESP32 Arduino Sketch Example
```cpp
void setup() {
  Serial.begin(115200);
}

void loop() {
  int gsr = analogRead(A0);
  float spo2 = readSpO2();  // Your sensor function
  float temp = readTemp();   // Your sensor function
  float ax = readAccelX();   // Your sensor function
  // ... read AY, AZ
  
  Serial.printf("GSR:%d,SPO2:%.1f,TEMP:%.1f,AX:%.2f,AY:%.2f,AZ:%.2f\n",
                gsr, spo2, temp, ax, ay, az);
  
  delay(1000);  // 1 sample per second
}
```

### Auto-Detection
The app automatically:
1. Scans all COM ports at startup
2. Tries to connect at 115200 baud
3. If successful → "ESP32 Connected — Live Mode"
4. If timeout (≥3s) → Switches to simulation mode

## Model Architecture

```
Input (500, 4)
    ↓
Conv1D(32) + BatchNorm + MaxPool(2) → (250, 32)
    ↓
Conv1D(64) + BatchNorm + MaxPool(2) → (125, 64)
    ↓
GlobalAveragePooling → (64,)
    ↓
Channel Attention Vector (CAV) → (4,)  [Weights per sensor]
    ↓
Weighted Input × CAV
    ↓
BiLSTM(32, bidirectional) → (64,)
    ↓
Dropout(0.4) [MC-Dropout]
    ↓
Dense(32, ReLU)
    ↓
Dense(4, Softmax) → [Class Probs (4,), CAV (4,)]
```

**Key Features:**
- **Channel Attention (PAST)** — Learns which sensors matter most
- **BiLSTM** — Captures temporal dynamics in sensor signals
- **MC-Dropout** — Provides uncertainty estimates via 20 stochastic forward passes
- **Sync PCS** — Per-channel similarity score to detect sensor conflicts

## Troubleshooting

### "No module named 'tensorflow'"
```bash
pip install tensorflow
```

### "SerialNotFoundError: No ESP32 detected"
- Check USB cable connection
- Verify COM port in Device Manager (Windows)
- Confirm baud rate is 115200
- App should auto-fallback to simulation mode after 3 seconds

### "ModuleNotFoundError: No module named 'streamlit'"
```bash
pip install streamlit
```

### Model training is slow / crashes
- Reduce windows_per_class in train_model.py (default 310 → 100)
- Reduce epochs (default 5 → 2)
- Increase batch_size (default 32 → 64)
- Close other applications to free RAM

### Dashboard shows wrong class probabilities
- Increase MC Dropout Passes slider (default 10 → 20)
- This gives the model more stochastic samples to average

### Sensor readings are stuck/not changing
- Check "Reading Interval" slider (is it 10s?)
- Verify ESP32 is actually streaming data: Use serial monitor at 115200 baud
- Restart the dashboard: Stop streamlit and run again

## File Structure
```
project_root/
├── app.py                          # Main Streamlit dashboard
├── requirements.txt                # Dependencies
├── README.md                       # Project overview
├── DEMO_INSTRUCTIONS.md            # This file
├── model/
│   ├── model_utils.py              # Core model + predict + PCS functions
│   ├── train_model.py              # Training script (generates synthetic data)
│   └── saved/
│       ├── ans_model.h5            # Trained model weights (generated after first run)
│       └── .gitkeep                # Placeholder
├── serial_reader/
│   ├── esp32_reader.py             # Hardware serial communication
│   ├── simulator.py                # Synthetic data generation (4 modes)
│   └── __init__.py
└── venv/                           # Virtual environment (not tracked in git)
```

## Exporting Results

### JSON Export
Click **"📥 Export Last Reading"** in the sidebar to download the latest prediction:

```json
{
  "predicted_class": "Normal Baseline",
  "confidence": 94.2,
  "variance": 0.0032,
  "low_confidence": false,
  "cav": {
    "GSR": 0.42,
    "SpO2": 0.31,
    "Temp": 0.15,
    "Accel": 0.12
  },
  "dominant_sensor": "GSR",
  "all_probs": {
    "Normal Baseline": 0.942,
    "Sympathetic Arousal": 0.038,
    "Parasympathetic Suppression": 0.015,
    "Mixed Dysregulation": 0.005
  },
  "pcs": 0.78,
  "sensor_conflict": false
}
```

## Performance Notes
- **Inference latency:** ~100-200ms per reading (with MC-Dropout T=20)
- **Memory usage:** ~500MB (model + streamlit + data)
- **CPU:** Single-threaded, ~40% on i7 @ MC-Dropout T=20
- **Update frequency:** User-configurable 1-10 seconds

## References
- Model: 1D-CNN + PAST (Per-Channel Attention) + BiLSTM
- Uncertainty: Monte Carlo Dropout (Gal & Ghahramani, 2016)
- Explainability: Channel Attention Vector weights + Per-Channel Similarity (PCS)

---

**Support:** For issues or questions, check the GitHub repository or open an issue.
