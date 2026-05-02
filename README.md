# ANS State Classification - Live Dashboard with Channel Attention

A real-time clinical decision support system for Autonomic Nervous System (ANS) state classification leveraging deep learning with channel attention mechanisms on wearable platforms (ESP32). This system continuously monitors multiple physiological sensors and provides AI-driven clinical narratives through a professional web dashboard.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Hardware Configuration](#hardware-configuration)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

---

## 🎯 Overview

This project implements a clinical-grade ANS state classification system combining:

- **Deep Learning Model**: Channel attention-based neural network for physiological signal interpretation
- **Real-time Data Acquisition**: Live sensor streaming from ESP32 microcontroller via USB serial interface
- **Interactive Dashboard**: Streamlit-based web interface with real-time visualization and clinical narratives
- **AI-Powered Insights**: Integration with Groq LLM for automated clinical interpretation
- **Wearable-Optimized**: Lightweight models suitable for deployment on resource-constrained edge devices

### ANS States Detected

The system classifies physiological data into distinct ANS states:
- Sympathetic Dominant (Fight/Flight)
- Parasympathetic Dominant (Rest/Digest)
- Balanced (Homeostatic)
- Transition States

---

## ✨ Features

- **Live Sensor Monitoring**: Real-time data streaming from multiple ESP32 sensors
  - GSR (Galvanic Skin Response)
  - SpO2 (Blood Oxygen Saturation)
  - Temperature
  - Accelerometer (3-axis)
  - Heart Rate (BPM)

- **Dual-Mode Operation**:
  - **Live Mode**: Connected ESP32 providing real sensor data
  - **Simulation Mode**: Synthetic data generation for development and testing

- **Auto-Detection & Reconnection**: Automatic ESP32 discovery with graceful fallback to simulation mode

- **Clinical Dashboard**:
  - Real-time waveform visualization
  - State probability distributions
  - Historical trend analysis
  - Sensor health monitoring

- **AI Clinical Narratives**: Automated interpretation of physiological patterns via LLM integration

- **SHAP Explainability**: Feature importance analysis for model predictions

- **Performance Monitoring**: Real-time metrics and system diagnostics

---

## 💻 System Requirements

### Minimum Hardware
- CPU: Intel/AMD processor (2+ cores, 2 GHz+)
- RAM: 4 GB
- Storage: 1 GB free space
- OS: Windows 10/11, Linux, or macOS

### Software Prerequisites
- **Python**: 3.8 or higher
- **pip**: Package manager for Python
- **Git**: For version control

### Optional Hardware
- **ESP32 Development Board**: For live sensor data acquisition
- **USB Cable**: Type-A to Micro-B (for ESP32 connection)

---

## 📦 Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/Anandhu-p-tec/Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms.git
cd Deep-Learning-with-Live-Channel-Attention-ANS-State-Classification-on-Wearable-Platforms
```

### Step 2: Create Python Virtual Environment

```powershell
# Windows
python -m venv venv
.\venv\Scripts\Activate.ps1

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies Include:**
- `tensorflow==2.14.0` - Deep learning framework
- `streamlit==1.32.0` - Web dashboard framework
- `numpy==1.26.4` - Numerical computing
- `pandas==2.2.1` - Data manipulation
- `scikit-learn==1.3.2` - ML utilities
- `pyserial==3.5` - Serial communication
- `plotly==5.20.0` - Interactive visualizations
- `groq==0.5.0` - LLM API client
- `shap==0.44.0` - Model explainability

### Step 4: Configure Environment Variables

Create a `.env` file in the project root:

```ini
GROQ_API_KEY=your_groq_api_key_here
ESP32_PORT=COM3
ESP32_BAUDRATE=115200
ANS_SAFE_UI_MODE=1
```

**Configuration Details:**
- `GROQ_API_KEY`: Required for clinical narrative generation. Get your key from [Groq Console](https://console.groq.com)
- `ESP32_PORT`: Serial port (e.g., COM3, /dev/ttyUSB0)
- `ESP32_BAUDRATE`: Default 115200 bps for ESP32
- `ANS_SAFE_UI_MODE`: Set to 1 for stable UI (fragments disabled)

---

## 🚀 Quick Start

### Launch the Dashboard (Windows)

```powershell
.\run_demo.ps1
```

### Launch the Dashboard (Linux/macOS)

```bash
bash run_demo.sh
```

### Access the Application

Open your browser and navigate to:
```
http://localhost:8511
```

---

## 📊 Usage

### With ESP32 Hardware Connected

1. Connect ESP32 via USB
2. Verify serial connection: Check `.env` file for correct `ESP32_PORT`
3. Launch dashboard
4. Dashboard will show **● ESP32 Live** status
5. Live sensor data streams and real-time classification begins

### Without Hardware (Simulation Mode)

1. Launch dashboard without ESP32 connected
2. Dashboard automatically enters **◎ Simulation Mode**
3. Synthetic sensor data generates realistic ANS patterns
4. Perfect for testing and development

### Dashboard Navigation

- **Sensor Tab**: Real-time waveforms and raw sensor values
- **Predictions Tab**: ANS state classification with confidence scores
- **Clinical Tab**: AI-generated clinical interpretation
- **Analytics Tab**: Historical trends and SHAP explanations
- **Settings Tab**: Port configuration and mode selection

---

## 📁 Project Structure

```
.
├── app.py                           # Main Streamlit application
├── requirements.txt                 # Python dependencies
├── .env                             # Environment configuration
├── run_demo.ps1                     # Windows launch script
│
├── model/
│   ├── model_utils.py               # Model architecture and utilities
│   ├── train_model.py               # Model training pipeline
│   └── saved/
│       ├── ans_model.h5             # Trained model weights
│       └── ans_model.weights.h5     # TensorFlow weights file
│
├── serial_reader/
│   ├── esp32_reader.py              # ESP32 communication handler
│   ├── serial_thread.py             # Background serial thread
│   └── simulator.py                 # Synthetic data generator
│
└── final_year_esp32_code/
    └── final_year_esp32_code.ino    # ESP32 firmware code
```

---

## 🔧 Hardware Configuration

### ESP32 Sensor Setup

The ESP32 firmware (`final_year_esp32_code/final_year_esp32_code.ino`) interfaces with:

**Analog Sensors:**
- ADC0: GSR sensor (galvanic skin response)
- ADC1: Temperature sensor (analog)
- ADC2: SpO2 sensor input

**Digital Sensors:**
- I2C: Accelerometer (MPU6050 or similar)
- I2C: Heart rate sensor (if equipped)

### USB Connection

1. Connect ESP32 to PC via USB (Micro-B cable)
2. Windows: Check Device Manager for COM port
3. Linux/macOS: Check `/dev/ttyUSB*` or `/dev/ttyACM*`
4. Update `ESP32_PORT` in `.env` file

### Serial Communication Protocol

- **Baud Rate**: 115200 bps
- **Data Format**: JSON frames (one per line)
- **Frame Structure**: `{"gsr": X, "spo2": Y, "temp": Z, "accel": [ax, ay, az], "bpm": B}`

---

## 🐛 Troubleshooting

### Issue: "No serial port available"

**Solution:**
- Verify ESP32 is connected via USB
- Check Device Manager (Windows) or `dmesg` (Linux)
- Install CH340 drivers if ESP32 not recognized
- Update `ESP32_PORT` in `.env` file

### Issue: Dashboard shows "Simulation Mode"

**Causes:**
- ESP32 not connected (expected behavior)
- Serial port misconfigured
- Serial communication error

**Solutions:**
1. Verify hardware connection
2. Check `.env` port configuration
3. Monitor terminal for error messages
4. Click "Reconnect" button in dashboard

### Issue: TensorFlow/CUDA errors

**Solution:**
```bash
# Reinstall TensorFlow with CPU support
pip uninstall tensorflow -y
pip install tensorflow==2.14.0 --index-url https://pypi.org/simple/
```

### Issue: Streamlit port already in use

**Solution:**
```bash
streamlit run app.py --server.port 8512
```

---

## 🧠 Architecture

### Deep Learning Model

**Model Type:** Convolutional Neural Network with Channel Attention

- **Input Shape**: (128, 6) - 128 time steps × 6 sensor channels
- **Channel Attention**: Recalibrates channel relationships dynamically
- **Output Layer**: 4 neurons (ANS state classes)
- **Activation**: Softmax

### Data Normalization

Sensor values normalized to hardware-calibrated ranges:
- **GSR**: 0-1000 Ω
- **SpO2**: 95-100%
- **Temperature**: 32-42°C
- **Accelerometer**: ±16 g

### Inference Pipeline

```
Raw Sensor Data → Windowing → Normalization → Model → 
State Probabilities → Post-processing → Clinical Narrative
```

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/improvement`
3. Commit changes: `git commit -m "Add feature description"`
4. Push to branch: `git push origin feature/improvement`
5. Submit a Pull Request

---

## 📝 License

This project is licensed under the MIT License. See LICENSE file for details.

---

## 📚 References

- TensorFlow Documentation: https://www.tensorflow.org/
- Streamlit Documentation: https://docs.streamlit.io/
- ESP32 Arduino Core: https://github.com/espressif/arduino-esp32
- SHAP Documentation: https://shap.readthedocs.io/

---

## ✉️ Support

For issues, questions, or suggestions, please open an issue on GitHub or contact the development team.

**Last Updated:** May 2, 2026  
**Version:** 1.0.0