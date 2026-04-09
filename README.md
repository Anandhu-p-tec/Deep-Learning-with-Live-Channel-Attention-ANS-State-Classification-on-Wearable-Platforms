# ANS State Classification - Live Dashboard
## Setup
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
streamlit run app.py
```
## Hardware
Connect ESP32 via USB. App auto-detects port.
If no hardware connected, app runs in simulation mode automatically.