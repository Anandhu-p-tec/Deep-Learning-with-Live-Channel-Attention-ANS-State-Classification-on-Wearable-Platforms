"""
ANS State Classification - Live Dashboard
Real-time monitoring of Autonomic Nervous System states via wearable sensors.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

import numpy as np
import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from model.model_utils import (
    CLASSES,
    CLASS_COLORS,
    SENSOR_NAMES,
    load_or_create_model,
    mc_dropout_predict,
    compute_pcs,
    get_dominant_channel_info,
)
from serial_reader.simulator import get_simulated_window
from serial_reader.esp32_reader import ESP32Reader, has_device
from groq_interpreter import get_clinical_interpretation

# Load environment variables
load_dotenv()
GROQ_API_KEY_ENV = os.getenv("GROQ_API_KEY")


# Page config
st.set_page_config(
    page_title="ANS State Monitor",
    page_icon="❤️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize session state
if "history" not in st.session_state:
    st.session_state.history = []
if "mode" not in st.session_state:
    st.session_state.mode = "auto"
if "last_result" not in st.session_state:
    st.session_state.last_result = None


@st.cache_resource
def load_model():
    """Load or create model with spinner."""
    with st.spinner("Loading AI model..."):
        return load_or_create_model()


def get_mode_and_sim_state() -> tuple[str, Optional[str]]:
    """Detect mode and get simulation state."""
    if st.session_state.mode == "auto":
        st.session_state.mode = "hardware" if has_device() else "simulation"
    
    mode = st.session_state.mode
    sim_state = None
    
    if mode == "simulation":
        sim_state = st.sidebar.selectbox(
            "Simulate physiological state:",
            [
                "normal_baseline",
                "sympathetic_arousal",
                "parasympathetic_suppression",
                "mixed_dysregulation",
            ],
            format_func=lambda x: x.replace("_", " ").title(),
        )
    
    return mode, sim_state


def render_status_badge(mode: str):
    """Render connection status badge."""
    if mode == "hardware":
        st.markdown(
            "<div style='background: #2ecc71; color: white; padding: 8px 16px; border-radius: 4px; width: fit-content;'>"
            "<b>🟢 ESP32 Connected — Live Mode</b></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='background: #f39c12; color: white; padding: 8px 16px; border-radius: 4px; width: fit-content;'>"
            "<b>🟡 Simulation Mode — No Hardware Detected</b></div>",
            unsafe_allow_html=True,
        )


def render_metric_cards(prediction: dict, pcs: float, sensor_conflict: bool):
    """Render main metrics row."""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        state = prediction["predicted_class"]
        color = CLASS_COLORS[state]
        st.markdown(
            f"<h3 style='color: {color};'>{state.split()[0]}</h3>",
            unsafe_allow_html=True,
        )
        st.metric("ANS State", state, label_visibility="collapsed")
    
    with col2:
        conf = prediction["confidence"]
        delta_val = None
        if st.session_state.last_result:
            last_conf = st.session_state.last_result["confidence"]
            delta_val = conf - last_conf
        st.metric("Confidence", f"{conf}%", delta=delta_val)
    
    with col3:
        pcs_status = "✓ Coherent" if not sensor_conflict else "⚠ Conflict"
        st.metric("PCS Score", f"{pcs:.2f}", delta=pcs_status)
    
    with col4:
        uncertainty = prediction["variance"]
        alert = "LOW CONFIDENCE ⚠" if prediction["low_confidence"] else "OK"
        st.metric("Uncertainty", f"{uncertainty:.4f}", delta=alert)


def render_past_attribution(prediction: dict):
    """Render PAST sensor attribution section."""
    st.markdown("---")
    st.subheader("🎯 Sensor Contribution (PAST)")
    
    cav = prediction["cav"]
    dominant_sensor = prediction["dominant_sensor"]
    
    # Progress bars
    for sensor in SENSOR_NAMES:
        weight = cav[sensor]
        is_dominant = sensor == dominant_sensor
        label = f"**{sensor}** — {weight:.0%} {'← dominant' if is_dominant else ''}"
        st.progress(weight, text=label)
    
    # Plotly chart
    import plotly.graph_objects as go
    
    cav_values = [cav[name] for name in SENSOR_NAMES]
    colors = ["#1D9E75", "#D85A30", "#378ADD", "#9B59B6"]
    
    fig = go.Figure(
        data=[go.Bar(x=cav_values, y=SENSOR_NAMES, orientation="h", marker_color=colors)]
    )
    
    fig.update_layout(
        title="Channel Attention Weights",
        xaxis_title="Weight",
        yaxis_title="Sensor",
        height=300,
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
    )
    
    st.plotly_chart(fig, use_container_width=True)


def render_clinical_interpretation(interpretation: Optional[str], api_key_exists: bool):
    """Render clinical interpretation section."""
    st.markdown("---")
    st.subheader("🤖 Clinical Interpretation (AI)")
    
    if interpretation:
        st.info(interpretation)
        st.caption("Generated by Llama 3 via Groq — Not a medical diagnosis")
    elif api_key_exists:
        st.caption("⏳ Interpretation unavailable")
    # If no API key, render nothing (section is hidden)


def render_history_chart():
    """Render classification history chart."""
    st.markdown("---")
    st.subheader("📊 Classification History")
    
    if len(st.session_state.history) == 0:
        st.info("No history yet. Readings will appear here.")
        return
    
    import plotly.graph_objects as go
    
    fig = go.Figure()
    
    # Group by class
    class_readings = {class_name: [] for class_name in CLASSES}
    
    for i, reading in enumerate(st.session_state.history):
        class_name = reading["predicted_class"]
        class_readings[class_name].append((i, reading["confidence"]))
    
    # Add traces per class
    for class_name in CLASSES:
        readings = class_readings[class_name]
        if readings:
            x_vals = [r[0] for r in readings]
            y_vals = [r[1] for r in readings]
            
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=y_vals,
                    mode="markers+lines",
                    name=class_name,
                    marker=dict(size=8, color=CLASS_COLORS[class_name]),
                )
            )
    
    fig.update_layout(
        title="Confidence Over Time",
        xaxis_title="Reading #",
        yaxis_title="Confidence (%)",
        hovermode="x unified",
        height=400,
        paper_bgcolor="white",
    )
    
    st.plotly_chart(fig, use_container_width=True)


def render_alerts(prediction: dict, pcs: float, sensor_conflict: bool):
    """Render alerts in sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.subheader("🚨 System Alerts")
    
    alerts = []
    
    if prediction["low_confidence"]:
        alerts.append(("error", "⚠ LOW CONFIDENCE — Prediction unreliable"))
    
    if sensor_conflict:
        alerts.append(("warning", "⚠ SENSOR CONFLICT — Check sensor contact"))
    
    if (
        prediction["predicted_class"] == "Sympathetic Arousal"
        and prediction["confidence"] > 75
    ):
        alerts.append(("error", "🔴 ALERT — Sympathetic Arousal Detected"))
    
    if (
        prediction["predicted_class"] == "Parasympathetic Suppression"
        and prediction["confidence"] > 75
    ):
        alerts.append(("info", "🔵 ALERT — Parasympathetic Suppression Detected"))
    
    if alerts:
        for alert_type, message in alerts:
            if alert_type == "error":
                st.sidebar.error(message, icon="❌")
            elif alert_type == "warning":
                st.sidebar.warning(message, icon="⚠️")
            elif alert_type == "info":
                st.sidebar.info(message, icon="ℹ️")
    else:
        st.sidebar.success("✓ No alerts", icon="✅")


def render_controls():
    """Render sidebar controls."""
    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Controls")
    
    interval = st.sidebar.slider("Reading Interval (s)", 1, 10, 3)
    n_passes = st.sidebar.slider("MC Dropout Passes", 5, 20, 10)
    
    # Groq API Key Input
    st.sidebar.markdown("---")
    st.sidebar.subheader("🤖 AI Interpretation (Optional)")
    
    groq_key_input = st.sidebar.text_input(
        "Groq API Key",
        type="password",
        placeholder="Enter your Groq API key for clinical AI interpretation",
        help="Your key is never stored. Visit groq.com for a free API key.",
    )
    
    # Use input key if provided, otherwise use env key
    if groq_key_input:
        st.session_state.groq_key = groq_key_input
    elif not hasattr(st.session_state, "groq_key"):
        st.session_state.groq_key = GROQ_API_KEY_ENV
    
    if st.session_state.groq_key:
        st.sidebar.success("✓ Groq API key ready", icon="✅")
    
    st.sidebar.markdown("---")
    
    if st.sidebar.button("📥 Export Last Reading"):
        if st.session_state.last_result:
            json_str = json.dumps(st.session_state.last_result, indent=2)
            st.sidebar.download_button(
                label="Download JSON",
                data=json_str,
                file_name="ans_reading.json",
                mime="application/json",
            )
        else:
            st.sidebar.warning("No reading to export yet.")
    
    return interval, n_passes


def get_next_window(mode: str, sim_state: Optional[str]) -> Optional[np.ndarray]:
    """Fetch next sensor window."""
    try:
        if mode == "hardware":
            reader = ESP32Reader()
            window = reader.read_window(n_samples=500)
            reader.close()
            if window is None:
                st.warning("📡 Hardware disconnected — switched to simulation.")
                st.session_state.mode = "simulation"
                return get_simulated_window("normal_baseline", n_samples=500)
            return window
        else:
            return get_simulated_window(sim_state or "normal_baseline", n_samples=500)
    except Exception as e:
        st.error(f"Error reading sensor: {str(e)}")
        return None


def main():
    """Main app."""
    # Header
    st.title("❤️ ANS State Monitor")
    st.markdown("Autonomic Nervous System Classification — Live AI Analysis")
    
    # Sidebar setup
    mode, sim_state = get_mode_and_sim_state()
    render_status_badge(mode)
    interval, n_passes = render_controls()
    
    # Load model
    model = load_model()
    
    # Main loop
    try:
        # Fetch window
        window = get_next_window(mode, sim_state)
        if window is None:
            st.error("Failed to read sensor data.")
            return
        
        # Predict
        prediction = mc_dropout_predict(model, window, T=n_passes)
        pcs, sensor_conflict = compute_pcs(model, window)
        
        # Get clinical interpretation (optional, never crashes if no API key)
        groq_key = getattr(st.session_state, "groq_key", GROQ_API_KEY_ENV)
        interpretation = get_clinical_interpretation(
            predicted_class=prediction["predicted_class"],
            confidence=prediction["confidence"],
            cav_dict=prediction["cav"],
            pcs_score=pcs,
            sensor_conflict=sensor_conflict,
            low_confidence=prediction["low_confidence"],
            api_key=groq_key,
        )
        
        # Store result
        st.session_state.last_result = prediction.copy()
        st.session_state.last_result["pcs"] = pcs
        st.session_state.last_result["sensor_conflict"] = sensor_conflict
        
        # Append to history (keep last 20)
        st.session_state.history.append(st.session_state.last_result)
        if len(st.session_state.history) > 20:
            st.session_state.history = st.session_state.history[-20:]
        
        # Render main content
        render_metric_cards(prediction, pcs, sensor_conflict)
        render_past_attribution(prediction)
        render_clinical_interpretation(interpretation, bool(groq_key))
        render_history_chart()
        render_alerts(prediction, pcs, sensor_conflict)
        
        st.markdown("---")
        st.markdown(
            "<small>Model: 1D-CNN + PAST + BiLSTM | Inference: MC Dropout | Hardware: ESP32</small>",
            unsafe_allow_html=True,
        )
        
        # Refresh logic
        time.sleep(interval)
        st.rerun()
    
    except Exception as e:
        st.error(f"❌ Application error: {str(e)}")
        st.write("Please refresh the page or check your configuration.")


if __name__ == "__main__":
    main()
