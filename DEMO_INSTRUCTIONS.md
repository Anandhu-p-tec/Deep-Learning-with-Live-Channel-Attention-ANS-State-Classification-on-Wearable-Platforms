# ANS State Classification Dashboard — Demo Instructions

## Overview
This project implements a real-time Autonomic Nervous System (ANS) state classifier using deep learning. The system monitors wearable sensor data (GSR, SpO2, Temp, Accel) and classifies ANS states:
- **Normal Baseline** — Relaxed, balanced state
- **Sympathetic Arousal** — High stress, alert state
- **Parasympathetic Suppression** — Suppressed parasympathetic function
- **Mixed Dysregulation** — Conflicting ANS signals

## Hardware Requirements (Optional)
- **ESP32 microcontroller** with ADC-connected sensors
- **USB cable** for serial communication (115200 baud)

If no ESP32 is connected, the app automatically runs in **simulation mode**.

## First-Time Setup

### 1. Navigate to Project Directory
```bash
cd Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms
```

### 2. Activate Virtual Environment
**Windows:**
```powershell
.\venv\Scripts\Activate.ps1
```

**macOS/Linux:**
```bash
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

**Note:** If pip fails due to GCC errors, install individual packages with pre-built wheels:
```bash
pip install --only-binary :all: numpy scipy scikit-learn pandas plotly pyserial streamlit
pip install tensorflow shap
```

### 4. Train the Model (First Run Only)
This generates synthetic training data and trains the ANS classifier:
```bash
python model/train_model.py
```

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
