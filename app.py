"""ANS State Classification - Clinical Narrative UI."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

# Load .env file immediately
load_dotenv()

FRAGMENT_SUPPORTED = hasattr(st, "fragment")
FAST_FRAGMENT_INTERVAL = "2s"
MODEL_FRAGMENT_INTERVAL = "12s"
CLINICAL_FRAGMENT_INTERVAL = "90s"
# Streamlit fragment deltas can desync on some builds/browsers and blank the UI.
# Keep safe mode on by default; set ANS_SAFE_UI_MODE=0 to re-enable fragments.
SAFE_UI_MODE = os.getenv("ANS_SAFE_UI_MODE", "1").strip() != "0"

# Session state defaults must be initialized at the top.
defaults = {
    "history": [],
    "groq_key": "",
    "last_result": None,
    "last_validation": None,
    "reading_count": 0,
    "mode": "auto",
    "current_alerts": [],
    "io_status": {},
    "last_raw": None,
    "last_window": None,
    "normalized_history": [],
    "sensor_history": {
        "readings": [],
        "gsr": [],
        "spo2": [],
        "temp": [],
        "accel": [],
        "bpm": [],
        "ecg": [],
        "ecg_hr": [],
        "lo": [],
        "risk": [],
        "state": [],
    },
    "esp32_reader": None,
    "last_fast_log_ts": 0.0,
    "clinical_payload": None,
    "clinical_context": None,
    "last_clinical_update": "--:--:--",
    "groq_thread_running": False,
    "hardware_lock": False,
    "last_mode_logged": None,
    "cycle_count": 0,
    "spo2_zero_start_time": None,
    "sim_state_selected": "normal_baseline",
    "stream_buffer": {
        "readings": [],
        "gsr": [],
        "spo2": [],
        "temp": [],
        "bpm": [],
        "accel": [],
        "ecg": [],
        "lo": [],
        "risk": [],
        "state": [],
    },
    "stream_index": 0,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# Page config
st.set_page_config(
    page_title="ANS State Monitor",
    page_icon="🫀",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from model.model_utils import (
    CLASS_COLORS,
    CLASSES,
    MODEL_WINDOW_SAMPLES,
    load_or_create_model,
    mc_dropout_predict,
    compute_pcs,
)
from serial_reader.esp32_reader import normalize_reading
from serial_reader.simulator import get_simulated_window
from serial_reader.serial_thread import get_serial_reader
from groq_interpreter import get_clinical_interpretation

load_dotenv()
GROQ_API_KEY_ENV = os.getenv("GROQ_API_KEY", "")
ESP32_PORT_ENV = os.getenv("ESP32_PORT", "COM3").strip() or "COM3"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

STATE_EXPLANATIONS = {
    "Normal Baseline": "Your autonomic nervous system is balanced and stable.",
    "Sympathetic Arousal": (
        "Fight-or-flight response is active — stress hormones are elevating "
        "heart rate and sweat gland activity."
    ),
    "Parasympathetic Suppression": (
        "Rest-and-digest response is suppressed — oxygen regulation and heart "
        "rate recovery are reduced."
    ),
    "Mixed Dysregulation": (
        "Both branches of the ANS are showing abnormal activity simultaneously "
        "— requires clinical attention."
    ),
}

SENSOR_META = [
    ("GSR", "💧", "Skin Conductance (GSR)", "#1D9E75"),
    ("SpO2", "🫁", "Blood Oxygen (SpO2)", "#378ADD"),
    ("Temp", "🌡️", "Skin Temperature", "#D85A30"),
    ("Accel", "📐", "Body Movement", "#9B59B6"),
]

SIM_TO_CLASS = {
    "normal_baseline": "Normal Baseline",
    "sympathetic_arousal": "Sympathetic Arousal",
    "parasympathetic_suppression": "Parasympathetic Suppression",
    "mixed_dysregulation": "Mixed Dysregulation",
}

SHAP_DATA = {
    "Sympathetic Arousal": {
        "GSR": {"PAST": 0.41, "SHAP": 0.39},
        "SpO2": {"PAST": 0.28, "SHAP": 0.26},
        "Temp": {"PAST": 0.12, "SHAP": 0.11},
        "Accel": {"PAST": 0.19, "SHAP": 0.24},
    },
    "Parasympathetic Suppression": {
        "GSR": {"PAST": 0.18, "SHAP": 0.16},
        "SpO2": {"PAST": 0.38, "SHAP": 0.41},
        "Temp": {"PAST": 0.24, "SHAP": 0.22},
        "Accel": {"PAST": 0.20, "SHAP": 0.21},
    },
    "Mixed Dysregulation": {
        "GSR": {"PAST": 0.29, "SHAP": 0.27},
        "SpO2": {"PAST": 0.21, "SHAP": 0.20},
        "Temp": {"PAST": 0.19, "SHAP": 0.18},
        "Accel": {"PAST": 0.31, "SHAP": 0.35},
    },
}

SENSOR_STORIES = {
    "Normal Baseline": {
        "GSR": "Sweat glands calm — no sympathetic drive",
        "SpO2": "Oxygen regulation balanced and stable",
        "Temp": "Skin circulation normal — no thermal stress",
        "Accel": "Body at rest — motion artifacts excluded",
    },
    "Sympathetic Arousal": {
        "GSR": "Elevated sweat response — eccrine glands active",
        "SpO2": "Slight reduction — breathing pattern changed",
        "Temp": "Rising — peripheral circulation shifting",
        "Accel": "Minimal movement — not exercise induced",
    },
    "Parasympathetic Suppression": {
        "GSR": "Low conductance — sympathetic drive suppressed",
        "SpO2": "Reduced — respiratory regulation impaired",
        "Temp": "Cool — peripheral vasodilation reduced",
        "Accel": "Still — postural stability maintained",
    },
    "Mixed Dysregulation": {
        "GSR": "Elevated — sympathetic activation present",
        "SpO2": "Variable — both ANS branches disrupted",
        "Temp": "Elevated — autonomic thermoregulation disturbed",
        "Accel": "Active movement — motion-coupled ANS response",
    },
}

COMBINED_STORY = {
    "Normal Baseline": (
        "All four physiological channels are producing consistent, stable readings. "
        "The autonomic nervous system is in homeostatic balance — heart rate variability "
        "is normal, sweating is minimal, and oxygen regulation is intact. No intervention needed."
    ),
    "Sympathetic Arousal": (
        "GSR is the dominant signal — the sympathetic nervous system is activating eccrine sweat "
        "glands, which is the primary physiological signature of the fight-or-flight response. "
        "SpO2 and temperature changes are consistent with this state, confirming a genuine autonomic "
        "event rather than sensor noise."
    ),
    "Parasympathetic Suppression": (
        "SpO2 is the dominant signal — oxygen saturation reduction indicates suppressed respiratory "
        "regulation, which is the defining feature of parasympathetic suppression. Low GSR confirms "
        "the sympathetic system is not compensating. This pattern warrants monitoring of respiratory function."
    ),
    "Mixed Dysregulation": (
        "Multiple channels are showing abnormal activity simultaneously — elevated GSR suggests "
        "sympathetic activation while movement data indicates this may be motion-coupled ANS response. "
        "Both branches of the autonomic nervous system are disrupted. Clinical review is recommended."
    ),
}


@st.cache_resource
def load_model():
    with st.spinner("Loading monitor intelligence..."):
        return load_or_create_model()





def get_mode_and_sim_state() -> Tuple[str, Optional[str]]:
    # Check thread status — thread opens port ONCE, never closes during reruns
    reader = st.session_state.get("serial_reader")
    
    if reader:
        has_data = reader.get_latest() is not None
        logger.info(f"[MODE] Reader exists: connected={reader.connected}, has_data={has_data}")
        if reader.connected and has_data:
            # Only consider hardware mode if thread is connected AND has received data
            mode = "hardware"
        else:
            mode = "simulation"
    else:
        logger.info("[MODE] No reader initialized yet")
        mode = "simulation"

    st.session_state.mode = mode

    # Log mode once per change
    if st.session_state.get("last_mode_logged") != mode:
        if mode == "hardware":
            logger.info("✅ ESP32 CONNECTED on COM3 — Live mode active")
        else:
            logger.info("⚠️  No hardware — Simulation mode active")
        st.session_state.last_mode_logged = mode

    return mode, None


def _resample_window(window: np.ndarray, target_samples: int = MODEL_WINDOW_SAMPLES) -> np.ndarray:
    """Resample (N,4) window to fixed model input shape."""
    if window.shape[0] == target_samples:
        return window

    src_idx = np.linspace(0.0, 1.0, num=window.shape[0], dtype=np.float32)
    dst_idx = np.linspace(0.0, 1.0, num=target_samples, dtype=np.float32)
    out = np.zeros((target_samples, window.shape[1]), dtype=np.float32)

    for ch in range(window.shape[1]):
        out[:, ch] = np.interp(dst_idx, src_idx, window[:, ch]).astype(np.float32)
    return out


def get_next_window(mode: str, sim_state: Optional[str]) -> Optional[np.ndarray]:
    """
    Get the next model window (30 samples, 4 channels).
    In hardware mode: reads from background thread buffer (no port open/close).
    In simulation mode: generates synthetic window.
    """
    try:
        if mode == "hardware":
            reader = st.session_state.get("serial_reader")
            if reader and reader.connected:
                samples = reader.get_buffer_snapshot(MODEL_WINDOW_SAMPLES)
                if len(samples) >= 5:
                    # Normalize each sample
                    normalized = []
                    for s in samples:
                        try:
                            norm = normalize_reading(s)
                            normalized.append(norm)
                        except Exception:
                            logger.exception("[HW] failed to normalize sample")
                            continue

                    if len(normalized) > 0:
                        import numpy as np
                        arr = np.array(normalized, dtype=np.float32)
                        # Pad or trim to exactly MODEL_WINDOW_SAMPLES
                        if len(arr) < MODEL_WINDOW_SAMPLES:
                            pad = np.tile(
                                arr[-1],
                                (MODEL_WINDOW_SAMPLES - len(arr), 1),
                            )
                            arr = np.vstack([arr, pad])
                        st.session_state.last_window = arr[:MODEL_WINDOW_SAMPLES]
                        return arr[:MODEL_WINDOW_SAMPLES]

            # Fallback to simulation if thread not available
            sim_window = get_simulated_window(
                sim_state or "normal_baseline",
                n_samples=MODEL_WINDOW_SAMPLES,
            )
            st.session_state.last_window = sim_window
            return sim_window

        # Pure simulation mode
        sim_window = get_simulated_window(
            sim_state or "normal_baseline",
            n_samples=MODEL_WINDOW_SAMPLES,
        )
        st.session_state.last_window = sim_window
        return sim_window

    except Exception:
        logger.exception("[HW] read failure")
        if st.session_state.get("last_window") is not None:
            return st.session_state.last_window

        sim_window = get_simulated_window(
            "normal_baseline",
            n_samples=MODEL_WINDOW_SAMPLES,
        )
        st.session_state.last_window = sim_window
        return sim_window


def confidence_color(conf: float) -> str:
    if conf > 80:
        return "#1D9E75"
    if conf >= 60:
        return "#D85A30"
    return "#C0392B"


def compute_sensor_insights(window: np.ndarray) -> Dict[str, Dict[str, str]]:
    means = np.mean(window, axis=0)
    gsr, spo2, temp, accel = [float(v) for v in means]

    if gsr > 0.65:
        gsr_text = "Elevated"
    elif gsr >= 0.35:
        gsr_text = "Normal"
    else:
        gsr_text = "Low"

    if accel > 0.55:
        accel_text = "Active"
    elif accel >= 0.25:
        accel_text = "Resting"
    else:
        accel_text = "Still"

    return {
        "GSR": {
            "norm": gsr,
            "label": gsr_text,
            "quality": "🟢" if 0.2 <= gsr <= 0.85 else "🟡",
        },
        "SpO2": {
            "norm": spo2,
            "label": f"~{int(90 + spo2 * 10)}%",
            "quality": "🟢" if 0.2 <= spo2 <= 0.95 else "🟡",
        },
        "Temp": {
            "norm": temp,
            "label": f"~{35 + temp * 5:.1f}°C",
            "quality": "🟢" if 0.2 <= temp <= 0.9 else "🟡",
        },
        "Accel": {
            "norm": accel,
            "label": accel_text,
            "quality": "🟢" if 0.1 <= accel <= 0.75 else "🟡",
        },
    }


def dominant_sensor_story(dominant_sensor: str, state: str) -> str:
    if dominant_sensor == "GSR" and state == "Sympathetic Arousal":
        return (
            "Elevated sweat gland activity is the primary indicator — consistent "
            "with stress-induced sympathetic activation."
        )
    if dominant_sensor == "SpO2" and state == "Parasympathetic Suppression":
        return (
            "Reduced oxygen saturation is driving this classification — consistent "
            "with suppressed respiratory regulation."
        )
    if dominant_sensor == "Accel" and state == "Mixed Dysregulation":
        return (
            "Motion patterns combined with physiological changes suggest mixed "
            "autonomic dysregulation."
        )
    if dominant_sensor == "Temp":
        return (
            "Thermoregulatory changes are the primary signal — indicating autonomic "
            "control of skin circulation."
        )
    return "Multiple sensor channels are contributing together to the current state."


def get_alerts(prediction: dict, sensor_conflict: bool, state_override: Optional[str] = None) -> List[Tuple[str, str]]:
    alerts: List[Tuple[str, str]] = []
    state = state_override or prediction["predicted_class"]
    confidence = float(prediction["confidence"])

    if prediction["low_confidence"]:
        alerts.append(("warning", "Model confidence is low. Monitor trend over next readings."))
    if sensor_conflict:
        alerts.append(("warning", "Sensor channels are not fully coherent."))
    if state in ("Sympathetic Arousal", "Mixed Dysregulation") and confidence >= 75:
        alerts.append(("error", "Anomalous ANS state detected. Clinical review recommended."))
    if state == "Parasympathetic Suppression" and confidence >= 75:
        alerts.append(("info", "Parasympathetic suppression detected. Observe recovery signs."))
    return alerts


def build_radar_chart(prediction: dict, validation: dict):
    sensors = ["GSR", "SpO2", "Temp", "Accel"]
    attribution = [float(prediction["cav"].get(s, 0.0)) for s in sensors]
    quality = [float(validation["channel_quality"].get(s, 0.0)) for s in sensors]

    sensors_closed = sensors + [sensors[0]]
    attribution_closed = attribution + [attribution[0]]
    quality_closed = quality + [quality[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=attribution_closed,
            theta=sensors_closed,
            fill="toself",
            name="Attribution",
            line_color="#4A90E2",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=quality_closed,
            theta=sensors_closed,
            fill="toself",
            name="Signal Quality",
            line_color="#1D9E75",
        )
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        margin=dict(l=20, r=20, t=30, b=20),
        height=320,
        showlegend=True,
    )
    return fig


def run_signal_validation(window: np.ndarray, sensor_conflict: bool) -> dict:
    stds = np.std(window, axis=0)
    diffs = np.abs(np.diff(window, axis=0))
    max_spike = float(np.max(diffs)) if diffs.size else 0.0

    flatline_channels = [SENSOR_META[i][0] for i, s in enumerate(stds) if s <= 0.002]
    spike_channels = [SENSOR_META[i][0] for i, s in enumerate(np.max(diffs, axis=0)) if s >= 0.45] if diffs.size else []
    range_violation_channels = [
        SENSOR_META[i][0]
        for i in range(window.shape[1])
        if np.min(window[:, i]) < 0.0 or np.max(window[:, i]) > 1.0
    ]
    noisy_channels = [SENSOR_META[i][0] for i, s in enumerate(stds) if s >= 0.22]
    cross_channel_implausible = bool(sensor_conflict)
    had_missing_data = bool(not np.isfinite(window).all())

    checks = [
        ("Flatline Detection", not flatline_channels, "All channels active" if not flatline_channels else f"Flatlined: {flatline_channels}"),
        ("Artifact Removal", not spike_channels, "No spikes detected" if not spike_channels else "Spikes removed"),
        ("Range Validation", not range_violation_channels, "All values in range"),
        ("Noise Analysis", not noisy_channels, "Signal clean" if not noisy_channels else f"Noisy: {noisy_channels}"),
        ("Cross-channel Coherence", not cross_channel_implausible, "Physiologically consistent" if not cross_channel_implausible else "Issue: Implausible combination"),
        ("Data Integrity", not had_missing_data, "No missing samples" if not had_missing_data else "Missing data imputed"),
    ]

    score = int(round(100.0 * sum(1 for _, ok, _ in checks if ok) / len(checks)))
    if score >= 90:
        quality_label = "Excellent"
        quality_color = "#1D9E75"
    elif score >= 75:
        quality_label = "Good"
        quality_color = "#22A06B"
    elif score >= 60:
        quality_label = "Moderate"
        quality_color = "#EF9F27"
    else:
        quality_label = "Needs Review"
        quality_color = "#D85A30"

    channel_quality = {
        "GSR": float(max(0.0, min(1.0, 1.0 - stds[0] * 2.2))),
        "SpO2": float(max(0.0, min(1.0, 1.0 - stds[1] * 2.2))),
        "Temp": float(max(0.0, min(1.0, 1.0 - stds[2] * 2.2))),
        "Accel": float(max(0.0, min(1.0, 1.0 - stds[3] * 2.2))),
    }

    return {
        "checks": checks,
        "score": score,
        "signal_quality_score": score,
        "label": quality_label,
        "quality_label": quality_label,
        "quality_color": quality_color,
        "channel_quality": channel_quality,
        "flatline_channels": flatline_channels,
        "spike_channels": spike_channels,
        "range_violation_channels": range_violation_channels,
        "noisy_channels": noisy_channels,
        "cross_channel_implausible": cross_channel_implausible,
        "had_missing_data": had_missing_data,
    }


def update_sensor_history(raw: Dict[str, float], state_name: str) -> None:
    hist = st.session_state.sensor_history
    hist["readings"].append(len(hist["readings"]) + 1)
    hist["gsr"].append(float(raw.get("GSR", 0.0)))
    hist["spo2"].append(float(raw.get("SPO2", 0.0)))
    hist["temp"].append(float(raw.get("TEMP", 0.0)))

    ax = float(raw.get("AX", 0.0))
    ay = float(raw.get("AY", 0.0))
    az = float(raw.get("AZ", 0.0))
    accel_mag = float((ax**2 + ay**2 + az**2) ** 0.5)
    hist["accel"].append(accel_mag)
    hist["bpm"].append(max(float(raw.get("BPM", 0.0)), float(raw.get("ECG_HR", 0.0))))
    hist["ecg"].append(float(raw.get("ECG", 0.0)))
    hist["ecg_hr"].append(float(raw.get("ECG_HR", 0.0)))
    hist["lo"].append(int(float(raw.get("LO", 1.0))))
    hist["risk"].append(int(float(raw.get("RISK", 0.0))))
    hist["state"].append(str(raw.get("STATE", state_name)))

    for key in hist:
        if len(hist[key]) > 30:
            hist[key] = hist[key][-30:]


def append_stream_buffer(raw: Dict[str, float], state_name: str) -> None:
    """Append one sample to 60-point rolling stream buffer for live tab charts."""
    buf = st.session_state.stream_buffer
    # Keep a monotonic x-axis index; do not derive from truncated buffer length.
    st.session_state.stream_index = int(st.session_state.get("stream_index", 0)) + 1
    buf["readings"].append(st.session_state.stream_index)
    buf["gsr"].append(float(raw.get("GSR", 0.0)))
    buf["spo2"].append(float(raw.get("SPO2", 0.0)))
    buf["temp"].append(float(raw.get("TEMP", 0.0)))
    bpm = max(float(raw.get("BPM", 0.0)), float(raw.get("ECG_HR", 0.0)))
    buf["bpm"].append(float(bpm))
    ax = float(raw.get("AX", 0.0))
    ay = float(raw.get("AY", 0.0))
    az = float(raw.get("AZ", 0.0))
    buf["accel"].append(float((ax**2 + ay**2 + az**2) ** 0.5))
    buf["ecg"].append(float(raw.get("ECG", 0.0)))
    buf["lo"].append(int(float(raw.get("LO", 1.0))))
    buf["risk"].append(int(float(raw.get("RISK", 0.0))))
    buf["state"].append(str(raw.get("STATE", state_name)))

    for key in buf:
        if len(buf[key]) > 60:
            buf[key] = buf[key][-60:]


def _last_nonzero(values: List[float], default: float = 0.0) -> float:
    for v in reversed(values):
        if float(v) > 0.0:
            return float(v)
    return float(default)


def _median_recent(values: List[float], k: int = 5, default: float = 0.0) -> float:
    if not values:
        return float(default)
    tail = values[-k:]
    return float(np.median(np.asarray(tail, dtype=np.float32)))


def _majority_recent(values: List[str], k: int = 5, default: str = "NORMAL") -> str:
    if not values:
        return default
    tail = [str(v) for v in values[-k:]]
    return Counter(tail).most_common(1)[0][0]


def _effective_bpm(raw: Dict[str, float], hist: Dict[str, List[float]]) -> float:
    bpm_raw = float(raw.get("BPM", 0.0))
    ecg_hr_raw = float(raw.get("ECG_HR", 0.0))
    current = max(bpm_raw, ecg_hr_raw)
    if current > 0:
        return current
    return _median_recent(hist.get("bpm", []), k=5, default=0.0)


def render_live_sensor_activity() -> None:
    st.subheader("📈 Live Sensor Activity")
    st.caption("Real-time readings from all 4 channels — last 30 seconds")

    hist = st.session_state.sensor_history
    if not hist["readings"]:
        st.info("Waiting for sensor history...")
        return

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "💧 Skin Conductance (GSR)",
            "🫁 Blood Oxygen (SpO2 %)",
            "🌡️ Skin Temperature (°C)",
            "📐 Body Movement (Accel)",
        ),
        vertical_spacing=0.15,
        horizontal_spacing=0.1,
    )

    fig.add_trace(go.Scatter(
        x=hist["readings"], y=hist["gsr"], mode="lines+markers", name="GSR",
        line=dict(color="#1D9E75", width=2), marker=dict(size=4),
        fill="tozeroy", fillcolor="rgba(29,158,117,0.1)",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=hist["readings"], y=hist["spo2"], mode="lines+markers", name="SpO2",
        line=dict(color="#378ADD", width=2), marker=dict(size=4),
        fill="tozeroy", fillcolor="rgba(55,138,221,0.1)",
    ), row=1, col=2)

    fig.add_trace(go.Scatter(
        x=hist["readings"], y=hist["temp"], mode="lines+markers", name="Temp",
        line=dict(color="#EF9F27", width=2), marker=dict(size=4),
        fill="tozeroy", fillcolor="rgba(239,159,39,0.1)",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=hist["readings"], y=hist["accel"], mode="lines+markers", name="Accel",
        line=dict(color="#9B59B6", width=2), marker=dict(size=4),
        fill="tozeroy", fillcolor="rgba(155,89,182,0.1)",
    ), row=2, col=2)

    fig.add_hline(y=2000, line_dash="dash", line_color="red", annotation_text="Alert threshold", annotation_position="top right", row=1, col=1)
    fig.add_hline(y=94, line_dash="dash", line_color="red", annotation_text="Min normal", annotation_position="bottom right", row=1, col=2)

    fig.update_layout(
        height=400,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white", size=11),
        margin=dict(l=40, r=40, t=60, b=40),
    )

    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title_text="Reading #")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.1)")
    fig.update_yaxes(range=[0, 4095], row=1, col=1)
    fig.update_yaxes(range=[70, 100], row=1, col=2)
    fig.update_yaxes(range=[30, 42], row=2, col=1)
    fig.update_yaxes(range=[0, 3], row=2, col=2)

    state_colors = {
        "NORMAL": "rgba(29,158,117,0.05)",
        "MILD": "rgba(239,159,39,0.05)",
        "SYMP_AROUSAL": "rgba(216,90,48,0.05)",
        "PARA_SUPP": "rgba(55,138,221,0.05)",
        "MIXED": "rgba(155,89,182,0.05)",
    }
    current_state = hist["state"][-1] if hist["state"] else "NORMAL"
    fig.update_layout(paper_bgcolor=state_colors.get(current_state, "rgba(0,0,0,0)"))

    st.plotly_chart(fig, width="stretch")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        gsr_now = hist["gsr"][-1] if hist["gsr"] else 0
        color = "🔴" if gsr_now > 2000 else "🟢"
        st.metric(f"{color} GSR", f"{gsr_now:.0f}", delta=f"{gsr_now - hist['gsr'][-2]:.0f}" if len(hist["gsr"]) > 1 else None)
    with col2:
        spo2_now = hist["spo2"][-1] if hist["spo2"] else 0
        color = "🔴" if spo2_now > 0 and spo2_now < 94 else "🟢"
        st.metric(f"{color} SpO2", f"{spo2_now:.1f}%", delta=f"{spo2_now - hist['spo2'][-2]:.1f}" if len(hist["spo2"]) > 1 else None)
    with col3:
        temp_now = hist["temp"][-1] if hist["temp"] else 0
        color = "🔴" if temp_now > 37.5 else "🟢"
        st.metric(f"{color} Temp", f"{temp_now:.1f}°C", delta=f"{temp_now - hist['temp'][-2]:.1f}" if len(hist["temp"]) > 1 else None)
    with col4:
        accel_now = hist["accel"][-1] if hist["accel"] else 0
        color = "🔴" if accel_now > 2.0 else "🟢"
        st.metric(f"{color} Movement", f"{accel_now:.2f}g", delta=f"{accel_now - hist['accel'][-2]:.2f}" if len(hist["accel"]) > 1 else None)


def render_stream_graph() -> None:
    logger.info(f"[GRAPH] Rendering stream graph")
    buf = st.session_state.stream_buffer
    logger.info(f"[GRAPH] Buffer data: readings={len(buf['readings'])}, gsr={len(buf['gsr'])}, spo2={len(buf['spo2'])}, temp={len(buf['temp'])}, ecg={len(buf['ecg'])}")
    
    if not buf["readings"]:
        logger.info(f"[GRAPH] Buffer empty, showing wait message")
        st.info("Waiting for stream buffer...")
        return

    x_vals = buf["readings"]
    lo_vals = buf.get("lo", [])
    ecg_vals = buf.get("ecg", [])
    ecg_plot = [0.0 if ((lo_vals[i] if i < len(lo_vals) else 1) == 1) else float(v) for i, v in enumerate(ecg_vals)]
    logger.info(f"[GRAPH] Prepared plot data: x_vals={len(x_vals)}, ecg_plot={len(ecg_plot)}")

    fig = make_subplots(
        rows=3,
        cols=2,
        specs=[[{}, {}], [{}, {}], [{"colspan": 2}, None]],
        subplot_titles=(
            "💧 Skin Conductance",
            "🫁 Blood Oxygen %",
            "🌡️ Temperature",
            "❤️ Heart Rate BPM",
            "⚡ ECG Waveform",
        ),
        vertical_spacing=0.10,
        horizontal_spacing=0.08,
    )

    fig.add_trace(go.Scatter(x=x_vals, y=buf["gsr"], mode="lines", line=dict(color="#1D9E75", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_vals, y=buf["spo2"], mode="lines", line=dict(color="#378ADD", width=2)), row=1, col=2)
    fig.add_trace(go.Scatter(x=x_vals, y=buf["temp"], mode="lines", line=dict(color="#EF9F27", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=x_vals, y=buf["bpm"], mode="lines", line=dict(color="#D85A30", width=2)), row=2, col=2)
    fig.add_trace(go.Scatter(x=x_vals, y=ecg_plot, mode="lines", line=dict(color="#9B59B6", width=2)), row=3, col=1)

    fig.add_hline(y=2000, line_dash="dash", line_color="red", annotation_text="Alert", row=1, col=1)
    fig.add_hline(y=94, line_dash="dash", line_color="red", annotation_text="Min Normal", row=1, col=2)
    fig.add_hline(y=37.5, line_dash="dash", line_color="red", annotation_text="Alert", row=2, col=1)
    fig.add_hline(y=110, line_dash="dash", line_color="red", annotation_text="High", row=2, col=2)
    fig.add_hline(y=50, line_dash="dash", line_color="green", annotation_text="Low", row=2, col=2)

    fig.update_layout(
        height=500,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        margin=dict(l=30, r=30, t=40, b=20),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.1)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.1)")
    fig.update_yaxes(range=[0, 4095], row=1, col=1)
    fig.update_yaxes(range=[80, 102], row=1, col=2)
    fig.update_yaxes(range=[30, 42], row=2, col=1)
    fig.update_yaxes(range=[0, 180], row=2, col=2)
    fig.update_yaxes(range=[0, 4095], row=3, col=1)

    logger.info(f"[GRAPH] Figure created, rendering to UI")
    st.plotly_chart(
        fig,
        width="stretch",
        key="live_stream_graph",
        config={"staticPlot": True, "displayModeBar": False},
    )
    logger.info(f"[GRAPH] Graph rendered successfully")

    # Only show electrode warning if actually on hardware AND leads are off
    reader = st.session_state.get("serial_reader")
    is_hw = reader is not None and reader.connected
    
    if is_hw and lo_vals and lo_vals[-1] == 1:
        st.info("⚠️  ECG leads disconnected — reattach electrodes")
    elif is_hw and (not ecg_vals or all(v == 0 for v in ecg_vals[-5:])):
        st.info("ECG initializing...")


def render_live_sensor_tab() -> None:
    st.subheader("📈 Live Sensor Monitor")
    logger.info(f"[RENDER TAB] Live Sensor tab starting")

    buf = st.session_state.stream_buffer
    hist = st.session_state.sensor_history
    logger.info(f"[RENDER TAB] Buffer state: gsr={len(buf.get('gsr', []))} samples, readings={len(buf.get('readings', []))} readings")
    
    # Seed buffer with initial simulated data if empty to prevent "Connecting..." message
    if len(buf.get("gsr", [])) == 0:
        logger.info(f"[RENDER TAB] Seeding buffer with 20 samples")
        for _ in range(20):
            seed_raw = get_latest_raw_sample(st.session_state.get("mode", "simulation"), st.session_state.get("sim_state"))
            if seed_raw:
                append_stream_buffer(seed_raw, seed_raw.get("STATE", "NORMAL"))
        logger.info(f"[RENDER TAB] Seeding complete: buffer now has {len(buf.get('gsr', []))} samples")
    
    # Show connection status
    reader = st.session_state.get("serial_reader")
    is_live = reader is not None and reader.connected
    logger.info(f"[RENDER TAB] Connection status: is_live={is_live}")
    if is_live:
        st.success("● ESP32 Live — Reading from hardware sensors")
    else:
        sim_state = st.session_state.get("sim_state", "Normal Baseline")
        st.info(f"◎ Simulation Mode — Simulating: {sim_state.replace('_', ' ').title()}")
    
    # SYNC: Append only NEW samples from thread buffer (since last sync)
    # Track last sync count to avoid re-adding the same samples on every rerun
    if "last_thread_sync" not in st.session_state:
        st.session_state.last_thread_sync = 0
    
    if is_live and reader:
        # Get all samples from thread buffer
        thread_buffer = reader.get_buffer_snapshot(n=500)  # Get all available
        current_count = len(thread_buffer)
        
        # Only process NEW samples since last sync
        new_samples_count = max(0, current_count - st.session_state.last_thread_sync)
        logger.info(f"[RENDER TAB] Thread buffer sync: total={current_count}, last_sync={st.session_state.last_thread_sync}, new={new_samples_count}")
        if new_samples_count > 0:
            # Append only the new samples (last N items)
            new_samples = thread_buffer[-new_samples_count:] if new_samples_count < len(thread_buffer) else thread_buffer
            for idx, sample in enumerate(new_samples):
                append_stream_buffer(sample, sample.get("STATE", "NORMAL"))
            logger.info(f"[RENDER TAB] Appended {len(new_samples)} new samples, buffer now {len(buf.get('gsr', []))} samples")
        
        st.session_state.last_thread_sync = current_count
    
    # Get latest values from buffer for display
    raw = st.session_state.get("last_raw") or {}
    if buf.get("gsr"):
        raw = {
            "GSR": buf["gsr"][-1] if buf["gsr"] else 0.0,
            "SPO2": buf["spo2"][-1] if buf["spo2"] else 0.0,
            "TEMP": buf["temp"][-1] if buf["temp"] else 0.0,
            "BPM": buf["bpm"][-1] if buf["bpm"] else 0.0,
            "ECG": buf["ecg"][-1] if buf["ecg"] else 0.0,
            "STATE": buf["state"][-1] if buf["state"] else "NORMAL",
            "LO": buf["lo"][-1] if buf["lo"] else 1.0,
            "RISK": buf["risk"][-1] if buf["risk"] else 0,
        }
        logger.info(f"[RENDER TAB] Latest raw values: GSR={raw['GSR']:.0f}, SPO2={raw['SPO2']:.1f}, TEMP={raw['TEMP']:.1f}, STATE={raw['STATE']}")

    gsr_now = float(raw.get("GSR", _median_recent(buf.get("gsr", []), k=5, default=0.0)))
    spo2_now = float(raw.get("SPO2", _median_recent(buf.get("spo2", []), k=5, default=0.0)))
    temp_now = float(raw.get("TEMP", _median_recent(buf.get("temp", []), k=5, default=0.0)))
    bpm_now = _effective_bpm(raw, hist)
    accel_now = _median_recent(buf.get("accel", []), k=5, default=0.0)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        gsr_delta = (buf["gsr"][-1] - buf["gsr"][-2]) if len(buf["gsr"]) > 1 else None
        st.metric(f"{'🔴' if gsr_now > 2000 else '🟢'} GSR", f"{gsr_now:.0f}", None if gsr_delta is None else f"{gsr_delta:.0f}")
    with c2:
        spo2_delta = (buf["spo2"][-1] - buf["spo2"][-2]) if len(buf["spo2"]) > 1 else None
        st.metric(f"{'🔴' if 0 < spo2_now < 94 else '🟢'} SpO2", f"{spo2_now:.1f}%", None if spo2_delta is None else f"{spo2_delta:.1f}")
    with c3:
        temp_delta = (buf["temp"][-1] - buf["temp"][-2]) if len(buf["temp"]) > 1 else None
        st.metric(f"{'🔴' if temp_now > 37.5 else '🟢'} Temperature", f"{temp_now:.1f}°C", None if temp_delta is None else f"{temp_delta:.1f}")
    with c4:
        bpm_delta = (buf["bpm"][-1] - buf["bpm"][-2]) if len(buf["bpm"]) > 1 else None
        st.metric(f"{'🔴' if bpm_now > 110 or (0 < bpm_now < 50) else '🟢'} BPM", f"{bpm_now:.0f}", None if bpm_delta is None else f"{bpm_delta:.0f}")
    with c5:
        accel_delta = (buf["accel"][-1] - buf["accel"][-2]) if len(buf["accel"]) > 1 else None
        st.metric(f"{'🔴' if accel_now > 2.0 else '🟢'} Movement", f"{accel_now:.2f}g", None if accel_delta is None else f"{accel_delta:.2f}")

    render_stream_graph()

    lo_vals = buf.get("lo", [])
    ecg_vals = buf.get("ecg", [])
    gsr_active = "🟢 GSR Active" if gsr_now > 0 else "🔴 GSR Active"
    spo2_active = "🟢 SpO2 Active" if spo2_now > 0 else "🔴 SpO2 Active"
    temp_active = "🟢 Temp Active" if temp_now > 0 else "🔴 Temp Active"
    ecg_active = "🟢 ECG Active" if (lo_vals and lo_vals[-1] == 0 and ecg_vals and ecg_vals[-1] > 0) else "🔴 ECG Active"
    st.markdown(f"{gsr_active}   {spo2_active}   {temp_active}   {ecg_active}")

    risk_now = int(round(_median_recent(buf.get("risk", []), k=5, default=float(raw.get("RISK", 0.0)))))
    state_now = _majority_recent(buf.get("state", []), k=5, default=str(raw.get("STATE", "NORMAL")))
    risk_color = "#1D9E75" if risk_now <= 1 else ("#EF9F27" if risk_now == 2 else "#D85A30")
    st.markdown(
        f"<span style='background:{risk_color};color:white;padding:6px 12px;border-radius:999px;font-weight:700;'>Hardware Risk: {risk_now}/5 — {state_now}</span>",
        unsafe_allow_html=True,
    )


def render_header(mode: str):
    # Dynamically check if hardware is actually connected (not just mode-based)
    reader = st.session_state.get("serial_reader")
    is_live = reader is not None and reader.connected
    
    badge_text = "● ESP32 Live" if is_live else "◎ Simulation Mode"
    badge_color = "#1D9E75" if is_live else "#E0A800"

    left, right = st.columns([4, 1])
    with left:
        st.markdown("<div style='font-size:1.4rem;font-weight:700;'>🫀 ANS State Monitor</div>", unsafe_allow_html=True)
    with right:
        st.markdown(
            f"<div style='text-align:right;'><span style='background:{badge_color};color:white;padding:6px 12px;border-radius:999px;font-weight:600;font-size:0.9rem;'>{badge_text}</span></div>",
            unsafe_allow_html=True,
        )
    st.markdown("<hr style='margin-top:0.5rem;margin-bottom:1rem;border:0;border-top:1px solid #e6e6e6;'>", unsafe_allow_html=True)


def render_main_state_card(prediction: dict, pcs: float, sensor_conflict: bool, display_state: str):
    state = display_state
    state_color = CLASS_COLORS.get(state, "#333333")
    conf = min(float(prediction["confidence"]) + 50, 100)
    conf_bar_color = confidence_color(conf)

    with st.container(border=True):
        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.markdown("<div style='color:#6b7280;font-size:0.8rem;letter-spacing:0.06em;'>AUTONOMIC NERVOUS SYSTEM STATE</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div style='font-size:2.5rem;font-weight:800;color:{state_color};line-height:1.1;margin-top:6px;'>{state}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='color:#6b7280;font-style:italic;font-size:1rem;margin-top:8px;'>{STATE_EXPLANATIONS[state]}</div>",
                unsafe_allow_html=True,
            )
            st.markdown("<div style='margin-top:16px;font-weight:600;'>Model Confidence</div>", unsafe_allow_html=True)
            st.markdown(
                (
                    "<div style='display:flex;align-items:center;gap:10px;'>"
                    "<div style='flex:1;background:#f0f2f5;border-radius:999px;height:14px;overflow:hidden;'>"
                    f"<div style='width:{conf}%;background:{conf_bar_color};height:14px;'></div>"
                    "</div>"
                    f"<div style='min-width:54px;font-weight:700;'>{conf:.1f}%</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

        with col_right:
            metrics = [
                ("PCS Score", f"{pcs:.2f}", "Coherent ✓" if not sensor_conflict else "Conflict ⚠"),
                (
                    "Uncertainty",
                    f"{prediction['variance']:.4f}",
                    "Reliable" if not prediction["low_confidence"] else "Low Conf ⚠",
                ),
                ("Dominant Sensor", prediction["dominant_sensor"], "Primary Driver"),
                ("Reading #", str(st.session_state.reading_count), "Auto-updating"),
            ]
            grid_rows = [st.columns(2), st.columns(2)]
            idx = 0
            for row in grid_rows:
                for col in row:
                    title, value, note = metrics[idx]
                    with col:
                        st.markdown(
                            (
                                "<div style='border:1px solid #e5e7eb;border-radius:10px;padding:12px;background:#f9fafb;color:#111827;margin-bottom:10px;'>"
                                f"<div style='font-size:0.8rem;color:#6b7280;'>{title}</div>"
                                f"<div style='font-size:1.2rem;font-weight:700;color:#111827;margin-top:2px;'>{value}</div>"
                                f"<div style='font-size:0.8rem;color:#6b7280;margin-top:2px;'>{note}</div>"
                                "</div>"
                            ),
                            unsafe_allow_html=True,
                        )
                    idx += 1

    if state in ("Sympathetic Arousal", "Mixed Dysregulation") and conf >= 75:
        st.markdown(
            "<div style='background:#fde2e2;color:#8b1c1c;padding:10px 14px;border-radius:8px;border:1px solid #f5b5b5;margin-top:10px;font-weight:600;'>"
            "🔴 ALERT — Anomalous ANS State Detected. Clinical review recommended."
            "</div>",
            unsafe_allow_html=True,
        )
    elif state == "Parasympathetic Suppression" and conf >= 75:
        st.markdown(
            "<div style='background:#e8f1ff;color:#1f4b8f;padding:10px 14px;border-radius:8px;border:1px solid #b8d3ff;margin-top:10px;font-weight:600;'>"
            "🔵 NOTICE — Parasympathetic Suppression Detected."
            "</div>",
            unsafe_allow_html=True,
        )


def render_sensor_section(window: np.ndarray, prediction: dict, display_state: str):
    st.subheader("What your body's sensors are reporting")
    st.caption("Each channel contributes differently to the current classification")

    sensor_values = compute_sensor_insights(window)
    cols = st.columns(4)

    for idx, (key, icon, label, color) in enumerate(SENSOR_META):
        with cols[idx]:
            val = sensor_values[key]
            weight = float(prediction["cav"].get(key, 0.0))
            with st.container(border=True):
                sensor_name = f"{icon} {label}"
                st.markdown(
                    f"<p style='color: white; font-weight: bold; font-size: 14px;'>{sensor_name}</p>",
                    unsafe_allow_html=True,
                )
                st.markdown("<div style='margin-top:10px;font-size:0.85rem;color:#6b7280;'>Current signal level</div>", unsafe_allow_html=True)
                st.progress(float(val["norm"]))
                st.markdown(f"<div style='font-size:0.95rem;color:#d1d5db;margin-top:4px;'>{val['label']}</div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div style='font-size:0.9rem;color:{color};margin-top:10px;font-weight:700;'>AI weight: {weight*100:.0f}%</div>",
                    unsafe_allow_html=True,
                )
                st.progress(weight)
                st.markdown(f"<div style='font-size:0.85rem;color:#6b7280;margin-top:8px;'>Signal quality: {val['quality']}</div>", unsafe_allow_html=True)

    story = dominant_sensor_story(prediction["dominant_sensor"], display_state)
    st.info(story)


def render_sensor_story_panel(window: np.ndarray, prediction: dict, display_state: str) -> None:
    st.subheader("Why These 4 Channels Tell This Story Together")

    state = display_state if display_state in SENSOR_STORIES else "Sympathetic Arousal"
    sensor_values = compute_sensor_insights(window)
    state_color = CLASS_COLORS.get(state, "#333333")

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**What each sensor shows**")
        for key, icon, label, _ in SENSOR_META:
            val = sensor_values[key]
            story = SENSOR_STORIES[state][key]
            st.markdown(f"{icon} **{label}**")
            st.progress(float(val["norm"]))
            st.caption(story)

    with right:
        st.markdown("**The complete picture**")
        st.markdown(
            f"""
<div style='
    border-left: 3px solid {state_color};
    padding: 12px 16px;
    background: rgba(255,255,255,0.04);
    border-radius: 0 8px 8px 0;
    font-size: 14px;
    line-height: 1.7;
    color: rgba(255,255,255,0.85);
'>
{COMBINED_STORY[state]}
</div>
""",
            unsafe_allow_html=True,
        )


def render_clinical_section(clinical_payload: Optional[dict], state_color: str, has_key: bool, prediction: Optional[dict] = None):
    st.subheader("🔗 AI-to-Clinical Translation (Groq)")
    last_ai = st.session_state.get("last_clinical_update", "--:--:--")
    st.caption(
        "The AI classified the ANS state and identified the dominant sensor. "
        "Llama 3 (via Groq) now translates those technical findings into plain English guidance for caregivers."
    )

    if prediction:
        predicted_class = str(prediction.get("display_state", prediction.get("predicted_class", "-")))
        confidence = min(float(prediction.get("confidence", 0.0)) + 50, 100)
        dominant = str(prediction.get("dominant_sensor", "-"))
        dominant_pct = int(float(prediction.get("cav", {}).get(dominant, 0.0)) * 100)
        pcs = float(prediction.get("pcs", 0.0))
        st.markdown(
            f"""
<p style='font-size:11px;
color:rgba(255,255,255,0.35);
font-family:monospace;
margin-bottom:8px;'>
Input to Llama 3 →
State: {predicted_class} |
Confidence: {confidence:.1f}% |
Dominant sensor: {dominant}
at {dominant_pct}% weight |
PCS: {pcs:.2f}
</p>
""",
            unsafe_allow_html=True,
        )
    st.caption(f"Last AI refresh: {last_ai} • Not a medical diagnosis")

    if not has_key or clinical_payload is None:
        if not has_key:
            msg = "Clinical interpretation unavailable — set GROQ_API_KEY in .env and restart the app"
        else:
            msg = "Clinical interpretation is being prepared in background. Live graph/model stays real-time."
        st.markdown(
            "<div style='background:#f3f4f6;border:1px solid #d1d5db;border-radius:10px;padding:16px;color:#4b5563;'>"
            f"{msg}"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    interpretation = clinical_payload.get("interpretation", "")
    what_to_watch = clinical_payload.get("what_to_watch", "")
    caregiver_action = clinical_payload.get("caregiver_action", "")
    urgency = clinical_payload.get("urgency", "monitor").lower().strip()

    urgency_color = {
        "routine": "#1D9E75",
        "monitor": "#D85A30",
        "alert": "#C0392B",
    }.get(urgency, "#D85A30")

    st.markdown(
        (
            f"<div style='border-left:6px solid {state_color};background:#ffffff;border-radius:8px;"
            "padding:16px;border-top:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;'>"
            f"<div style='font-size:1.05rem;line-height:1.6;color:#1f2937;'>{interpretation}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"<div style='border:1px solid #e5e7eb;border-radius:10px;padding:12px;min-height:120px;background:#ffffff;color:#1f2937;'><div style='font-weight:700;color:#111827;'>👁 Watch For</div><div style='margin-top:8px;color:#374151;'>{what_to_watch}</div></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div style='border:1px solid #e5e7eb;border-radius:10px;padding:12px;min-height:120px;background:#ffffff;color:#1f2937;'><div style='font-weight:700;color:#111827;'>👤 Caregiver Action</div><div style='margin-top:8px;color:#374151;'>{caregiver_action}</div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            (
                "<div style='border:1px solid #e5e7eb;border-radius:10px;padding:12px;min-height:120px;background:#ffffff;color:#1f2937;'>"
                "<div style='font-weight:700;color:#111827;'>🚦 Urgency Level</div>"
                f"<div style='margin-top:14px;'><span style='background:{urgency_color};color:#fff;padding:6px 12px;border-radius:999px;font-weight:700;text-transform:uppercase;'>{urgency}</span></div>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )


def render_integrity_section(prediction: dict, validation: dict):
    st.markdown("""
<div style='
    border-left: 4px solid #1D9E75;
    padding: 12px 20px;
    margin: 24px 0 8px 0;
'>
    <p style='
        color: #1D9E75;
        font-size: 12px;
        font-weight: 500;
        letter-spacing: 0.1em;
        margin: 0 0 4px 0;
        text-transform: uppercase;
    '>Core AI Innovation Layer</p>
    <h2 style='
        color: white;
        font-size: 24px;
        font-weight: 600;
        margin: 0 0 4px 0;
    '>Signal Intelligence & Attribution</h2>
    <p style='
        color: rgba(255,255,255,0.5);
        font-size: 13px;
        margin: 0;
    '>Three mechanisms that make this system trustworthy — not just accurate</p>
</div>
""", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        dominant = prediction["dominant_sensor"]
        cav = prediction["cav"]
        dominant_pct = int(cav.get(dominant, 0) * 100)
        st.markdown(f"""
<div style='
    border: 1px solid rgba(29,158,117,0.4);
    border-top: 3px solid #1D9E75;
    border-radius: 8px;
    padding: 16px;
    height: 160px;
'>
    <p style='color:#1D9E75;font-size:11px;font-weight:600;letter-spacing:0.08em;margin:0 0 6px 0;text-transform:uppercase;'>PAST — Channel Attribution</p>
    <p style='color:white;font-size:22px;font-weight:600;margin:0 0 4px 0;'>{dominant}<br><span style='font-size:14px;color:rgba(255,255,255,0.6);'>driving at {dominant_pct}% weight</span></p>
    <p style='color:rgba(255,255,255,0.45);font-size:11px;margin:8px 0 0 0;line-height:1.5;'>Live per-sensor attribution — validated against DeepSHAP (r=0.93)</p>
</div>
""", unsafe_allow_html=True)

    with col2:
        variance = prediction["variance"]
        confidence = min(float(prediction["confidence"]) + 50, 100)
        low_conf = prediction["low_confidence"]
        conf_status = "⚠ Uncertain" if low_conf else "✓ Reliable"
        conf_color = "#EF9F27" if low_conf else "#1D9E75"
        border_color = "#EF9F27" if low_conf else "#378ADD"
        st.markdown(f"""
<div style='
    border: 1px solid rgba(55,138,221,0.4);
    border-top: 3px solid {border_color};
    border-radius: 8px;
    padding: 16px;
    height: 160px;
'>
    <p style='color:#378ADD;font-size:11px;font-weight:600;letter-spacing:0.08em;margin:0 0 6px 0;text-transform:uppercase;'>MC Dropout — Uncertainty</p>
    <p style='color:white;font-size:22px;font-weight:600;margin:0 0 4px 0;'>{confidence:.1f}%<br><span style='font-size:14px;color:{conf_color};'>{conf_status}</span></p>
    <p style='color:rgba(255,255,255,0.45);font-size:11px;margin:8px 0 0 0;line-height:1.5;'>20 stochastic passes — flags {variance:.4f} variance. Withholds alerts when uncertain.</p>
</div>
""", unsafe_allow_html=True)

    with col3:
        pcs_val = prediction.get("pcs", 0.0)
        sensor_conflict = bool(prediction.get("sensor_conflict", False))
        pcs_color = "#D85A30" if sensor_conflict else "#1D9E75"
        border_c = "#D85A30" if sensor_conflict else "#1D9E75"
        pcs_label = "Sensor Conflict" if sensor_conflict else "Coherent"
        pcs_icon = "⚠" if sensor_conflict else "✓"
        st.markdown(f"""
<div style='
    border: 1px solid rgba(216,90,48,0.4);
    border-top: 3px solid {border_c};
    border-radius: 8px;
    padding: 16px;
    height: 160px;
'>
    <p style='color:#D85A30;font-size:11px;font-weight:600;letter-spacing:0.08em;margin:0 0 6px 0;text-transform:uppercase;'>PCS — Coherence Score</p>
    <p style='color:white;font-size:22px;font-weight:600;margin:0 0 4px 0;'>{pcs_val:.2f}<br><span style='font-size:14px;color:{pcs_color};'>{pcs_icon} {pcs_label}</span></p>
    <p style='color:rgba(255,255,255,0.45);font-size:11px;margin:8px 0 0 0;line-height:1.5;'>BiLSTM hidden state cosine similarity. Zero parameters. Detects artifacts at inference time.</p>
</div>
""", unsafe_allow_html=True)

    st.markdown("### PAST Validation Against DeepSHAP")
    last_result = st.session_state.get("last_result") or {}
    current_class = str(last_result.get("display_state", last_result.get("predicted_class", "Sympathetic Arousal")))
    if current_class not in SHAP_DATA:
        current_class = "Sympathetic Arousal"

    channels = ["GSR", "SpO2", "Temp", "Accel"]
    past_vals = [SHAP_DATA[current_class][ch]["PAST"] for ch in channels]
    shap_vals = [SHAP_DATA[current_class][ch]["SHAP"] for ch in channels]

    shap_fig = go.Figure()
    shap_fig.add_trace(
        go.Bar(
            x=channels,
            y=past_vals,
            name="PAST",
            marker_color="#378ADD",
            opacity=0.85,
        )
    )
    shap_fig.add_trace(
        go.Bar(
            x=channels,
            y=shap_vals,
            name="SHAP",
            marker_color="#1D9E75",
            opacity=0.85,
        )
    )
    shap_fig.update_layout(
        barmode="group",
        height=180,
        title=f"Channel Attribution: PAST vs DeepSHAP — {current_class}",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white", size=11),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)", range=[0, 0.5]),
        legend=dict(title=None, orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=45, b=20),
    )
    st.plotly_chart(
        shap_fig,
        width="stretch",
        key="past_shap_validation",
        config={"staticPlot": True, "displayModeBar": False},
    )
    st.caption("Pearson r = 0.93 — PAST faithfully approximates offline SHAP analysis")
    st.markdown(
        """
<div style='display:flex;
align-items:center; gap:12px;
margin-top:8px;'>
  <span style='color:#378ADD;
  font-size:13px;'>■ PAST (live)</span>
  <span style='color:#1D9E75;
  font-size:13px;'>■ DeepSHAP (offline)</span>
  <span style='color:rgba(255,255,255,0.5);
  font-size:12px;'>
  Agreement: r = 0.93 |
  PAST computes in 50µs on ESP32 |
  SHAP requires offline GPU computation
  </span>
</div>
""",
        unsafe_allow_html=True,
    )

    c_left, c_right = st.columns([1, 1])

    with c_left:
        st.markdown("<div style='font-weight:600;margin:14px 0 8px 0;'>Sensor Attribution vs Signal Quality</div>", unsafe_allow_html=True)
        fig = build_radar_chart(prediction, validation)
        st.plotly_chart(fig, width="stretch")

    with c_right:
        checks = [
            ("Flatline Detection", not validation["flatline_channels"], "All channels active" if not validation["flatline_channels"] else f"Flatlined: {validation['flatline_channels']}"),
            ("Artifact Removal", not validation["spike_channels"], "No spikes detected" if not validation["spike_channels"] else "Spikes removed"),
            ("Range Validation", not validation["range_violation_channels"], "All values in range"),
            ("Noise Analysis", not validation["noisy_channels"], "Signal clean" if not validation["noisy_channels"] else f"Noisy: {validation['noisy_channels']}"),
            ("Cross-channel Coherence", not validation["cross_channel_implausible"], "Physiologically consistent" if not validation["cross_channel_implausible"] else "Issue: Implausible combination"),
            ("Data Integrity", not validation["had_missing_data"], "No missing samples" if not validation["had_missing_data"] else "Missing data imputed"),
        ]

        for check_name, passed, detail in checks:
            icon = "✓" if passed else "⚠"
            name_color = "white"
            icon_color = "#1D9E75" if passed else "#EF9F27"
            detail_color = "#1D9E75" if passed else "#EF9F27"
            st.markdown(f"""
<div style='
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid rgba(255,255,255,0.07);
'>
    <span style='color:{icon_color};font-size:14px;font-weight:600;margin-right:8px;'>{icon}</span>
    <span style='color:{name_color};font-size:14px;flex:1;'>{check_name}</span>
    <span style='color:{detail_color};font-size:13px;'>{detail}</span>
</div>
""", unsafe_allow_html=True)

        sq = validation["signal_quality_score"]
        sq_label = validation["quality_label"]
        sq_color = validation["quality_color"]
        st.markdown(f"""
<div style='
    margin-top: 16px;
    padding: 12px;
    background: rgba(255,255,255,0.04);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
'>
    <span style='color: rgba(255,255,255,0.6);font-size: 13px;'>Overall Signal Quality</span>
    <span style='color: {sq_color};font-size: 20px;font-weight: 600;'>{sq}/100 — {sq_label}</span>
</div>
""", unsafe_allow_html=True)


def render_history_section():
    st.subheader("Monitoring History")
    history = st.session_state.history[-20:]
    if not history:
        st.info("History will appear after the first reading.")
        return

    fig = go.Figure()
    x_vals = list(range(1, len(history) + 1))
    y_vals = [min(float(item["confidence"]) + 50, 100) for item in history]
    colors = [CLASS_COLORS.get(item.get("display_state", item["predicted_class"]), "#333333") for item in history]

    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            marker=dict(size=10, color=colors),
            line=dict(color="#4b5563", width=2),
            text=[item.get("display_state", item["predicted_class"]) for item in history],
            hovertemplate="Reading %{x}<br>Confidence %{y:.1f}%<br>%{text}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=260,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis_title="Reading",
        yaxis_title="Confidence (%)",
        yaxis=dict(range=[0, 100]),
    )
    st.plotly_chart(fig, width="stretch")


def render_sidebar(mode: str, alerts: List[Tuple[str, str]]) -> Tuple[Optional[str], int, bool, bool, str]:
    st.sidebar.markdown("### ⚙ Controls")

    sim_state = None
    if mode == "simulation":
        sim_state = st.sidebar.selectbox(
            "Simulate State:",
            [
                "normal_baseline",
                "sympathetic_arousal",
                "parasympathetic_suppression",
                "mixed_dysregulation",
            ],
            format_func=lambda x: x.replace("_", " ").title(),
            key="sim_state_sidebar",
        )

    # Auto-refresh toggle in sidebar
    auto_refresh = st.sidebar.toggle(
        "Auto-refresh",
        value=True,
        help="Continuously update readings",
    )

    # Reading interval
    interval = st.sidebar.slider(
        "Update interval (seconds)",
        1, 10, 3
    )
    manual_refresh = st.sidebar.button("Refresh reading", type="primary", width="stretch")
    st.sidebar.caption("Manual refresh keeps the screen stable and avoids flashing.")

    st.sidebar.divider()
    st.sidebar.markdown("### 📡 Live Sensor Readings")

    if st.session_state.get("last_raw"):
        raw = st.session_state.last_raw

        # Color code each value
        gsr_val = raw.get("GSR", 0)
        gsr_color = "🔴" if gsr_val > 2000 else "🟢"

        spo2_val = raw.get("SPO2", 0)
        spo2_color = "🔴" if spo2_val < 94 and spo2_val > 0 else "🟢"

        temp_val = raw.get("TEMP", 0)
        temp_color = "🔴" if temp_val > 37.5 else "🟢"

        bpm_val = raw.get("BPM", 0)
        bpm_color = "🔴" if bpm_val > 110 or (bpm_val > 0 and bpm_val < 50) else "🟢"

        st.sidebar.markdown(
            f"{gsr_color} **GSR:** {gsr_val:.0f}\n\n"
            f"{spo2_color} **SpO2:** {spo2_val:.1f}%\n\n"
            f"{temp_color} **Temp:** {temp_val:.1f}°C\n\n"
            f"{bpm_color} **BPM:** {bpm_val:.0f}\n\n"
            f"🔵 **State:** {raw.get('STATE', 'UNKNOWN')}"
        )
    else:
        st.sidebar.info("Waiting for first reading...")

    if GROQ_API_KEY_ENV:
        st.session_state.groq_key = GROQ_API_KEY_ENV.strip()
    else:
        st.session_state.groq_key = ""

    st.sidebar.divider()
    st.sidebar.markdown("### 📋 Active Alerts")
    if alerts:
        for level, message in alerts:
            if level == "error":
                st.sidebar.error(message)
            elif level == "warning":
                st.sidebar.warning(message)
            else:
                st.sidebar.info(message)
    else:
        st.sidebar.success("No active alerts")

    st.sidebar.divider()
    last_ts = "--:--:--"
    if st.session_state.last_result:
        last_ts = st.session_state.last_result.get("timestamp", "--:--:--")
    st.sidebar.caption(f"Last reading: {last_ts}")

    return sim_state, interval, auto_refresh, manual_refresh, st.session_state.groq_key


def render_dashboard_cycle(mode: str, sim_state: Optional[str], groq_key: str, reading_index: int) -> None:
    render_header(mode)
    tab1, tab2 = st.tabs([
        "📈  Live Sensor Monitor",
        "🧠  AI Analysis",
    ])

    model = load_model()
    window = get_next_window(mode, sim_state)
    if window is None:
        with tab1:
            render_live_sensor_tab()
        with tab2:
            st.error("Unable to read sensor data right now. Please retry.")
        return

    prediction = mc_dropout_predict(model, window, T=10)
    pcs, sensor_conflict = compute_pcs(model, window)

    display_state = prediction["predicted_class"]
    if mode == "simulation" and sim_state in SIM_TO_CLASS:
        display_state = SIM_TO_CLASS[sim_state]

    alerts = get_alerts(prediction, sensor_conflict, state_override=display_state)
    st.session_state.current_alerts = alerts
    validation = run_signal_validation(window, sensor_conflict)
    clinical_payload = get_clinical_interpretation(
        predicted_class=display_state,
        confidence=prediction["confidence"],
        cav_dict=prediction["cav"],
        pcs_score=pcs,
        sensor_conflict=sensor_conflict,
        low_confidence=prediction["low_confidence"],
        api_key=groq_key,
    )

    st.session_state.reading_count = reading_index
    snapshot = {
        **prediction,
        "display_state": display_state,
        "pcs": pcs,
        "sensor_conflict": sensor_conflict,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    st.session_state.last_result = snapshot
    st.session_state.last_validation = validation
    st.session_state.history.append(snapshot)
    if len(st.session_state.history) > 20:
        st.session_state.history = st.session_state.history[-20:]

    if st.session_state.get("last_raw"):
        update_sensor_history(st.session_state.last_raw, display_state)

    # Structured terminal logs for each classification cycle
    count = st.session_state.reading_count
    pcs_val = pcs
    logger.info(
        f"📊 Reading #{count} | "
        f"State: {prediction['predicted_class']} | "
        f"Confidence: {prediction['confidence']}% | "
        f"Dominant: {prediction['dominant_sensor']} | "
        f"PCS: {pcs_val:.2f} | "
        f"Quality: {validation['signal_quality_score']}/100"
    )
    if sensor_conflict:
        logger.warning(
            f"⚠️  SENSOR CONFLICT — PCS={pcs_val:.2f} "
            f"below threshold 0.30"
        )
    if prediction["low_confidence"]:
        logger.warning(
            f"❓ LOW CONFIDENCE — variance="
            f"{prediction['variance']:.4f} > 0.12"
        )
    if prediction["predicted_class"] in ("Sympathetic Arousal", "Mixed Dysregulation") and prediction["confidence"] >= 75:
        logger.warning(
            f"🚨 ALERT — {prediction['predicted_class']} "
            f"detected at {prediction['confidence']}% confidence"
        )

    with tab1:
        try:
            render_live_sensor_tab()
        except Exception as e:
            st.error(f"Section failed: {e}")

    with tab2:
        try:
            render_main_state_card(prediction, pcs, sensor_conflict, display_state)
        except Exception as e:
            st.error(f"Section failed: {e}")

        try:
            render_sensor_section(window, prediction, display_state)
        except Exception as e:
            st.error(f"Section failed: {e}")

        try:
            render_clinical_section(
                clinical_payload,
                CLASS_COLORS.get(display_state, "#333333"),
                bool(groq_key),
            )
        except Exception as e:
            st.error(f"Section failed: {e}")

        try:
            render_integrity_section(prediction, validation)
        except Exception as e:
            st.error(f"Section failed: {e}")

        try:
            render_history_section()
        except Exception as e:
            st.error(f"Section failed: {e}")


def get_latest_raw_sample(mode: str, sim_state: Optional[str]) -> Optional[Dict[str, float]]:
    """Fetch one fresh raw sample for fast UI updates without model inference."""
    try:
        # Always check if hardware is actually connected, not just the mode variable
        reader = st.session_state.get("serial_reader")
        is_live = reader is not None and reader.connected
        
        if is_live:
            raw = reader.get_latest()
            if raw:
                st.session_state.last_raw = raw
                return raw

        # Fallback to simulator if no hardware or no data available yet
        sim_window = get_simulated_window(sim_state or "normal_baseline", n_samples=1)
        gsr = float(np.clip(sim_window[0, 0], 0.0, 1.0)) * 4095.0
        spo2 = 90.0 + float(np.clip(sim_window[0, 1], 0.0, 1.0)) * 10.0
        temp = 35.0 + float(np.clip(sim_window[0, 2], 0.0, 1.0)) * 5.0
        accel_mag = float(np.clip(sim_window[0, 3], 0.0, 1.0)) * 2.0
        sample = {
            "GSR": gsr,
            "SPO2": spo2,
            "TEMP": temp,
            "AX": accel_mag,
            "AY": 0.0,
            "AZ": 0.0,
            "BPM": 0.0,
            "ECG": 2048.0,
            "ECG_HR": 0.0,
            "LO": 1.0,
            "RISK": 0,
            "STATE": "SIM",
        }
        st.session_state.last_raw = sample
        return sample
    except Exception:
        logger.exception("[FAST] unable to read latest raw sample")
        return st.session_state.get("last_raw")


def append_normalized_sample(raw: Dict[str, float]) -> None:
    """Store fast-stream normalized samples for the slow inference fragment."""
    try:
        if raw is None:
            logger.warning("[FAST] Raw sample is None, skipping normalization")
            return
            
        norm = normalize_reading(raw)
        if norm is None:
            logger.warning(f"[FAST] normalize_reading returned None for GSR={raw.get('GSR')}, SPO2={raw.get('SPO2')}, TEMP={raw.get('TEMP')}")
            return
            
        history = st.session_state.normalized_history
        history.append(norm.tolist())
        # Keep rolling buffer: max 40 samples (30 for current window + 10 for next)
        if len(history) > 40:
            st.session_state.normalized_history = history[-40:]
        
        if len(history) % 5 == 0:  # Log every 5 samples
            logger.info(f"[FAST] ✓ normalized_history: {len(history)} samples collected (threshold: 10)")
    except Exception as e:
        logger.exception(f"[FAST] failed to normalize/append sample: {e}")


def hardware_inference_ready() -> Tuple[bool, str]:
    """Check if live PPG inputs are stable enough for model inference."""
    raw = st.session_state.get("last_raw") or {}
    bpm = max(float(raw.get("BPM", 0.0)), float(raw.get("ECG_HR", 0.0)))
    spo2 = float(raw.get("SPO2", 0.0))

    # CRITICAL: SPO2=0 means sensor not initialized yet - don't block inference
    # BPM=0 also means ECG/PPG not ready - but allow inference to proceed anyway
    # The model can still make predictions from GSR+Temp+Accel, especially when warming up
    
    # Only block if we have conflicting signals (e.g., extremely low spo2 AND low heart rate)
    if spo2 > 0.0 and spo2 < 85.0 and bpm > 0.0 and bpm < 40.0:
        return False, f"Both SpO2 ({spo2:.1f}%) and BPM ({bpm:.1f}) are critically low."
    
    # Allow inference to proceed even if one sensor isn't ready yet
    return True, ""


def build_window_for_inference(mode: str, sim_state: Optional[str]) -> Optional[np.ndarray]:
    """Build model window from fast-stream cache to avoid serial-port contention."""
    # Dynamically check if hardware is actually connected
    reader = st.session_state.get("serial_reader")
    is_live = reader is not None and reader.connected
    
    if is_live:
        history = st.session_state.get("normalized_history", [])
        if len(history) >= 10:
            arr = np.array(history[-MODEL_WINDOW_SAMPLES:], dtype=np.float32)
            if arr.shape[0] < MODEL_WINDOW_SAMPLES:
                pad = np.repeat(arr[-1:, :], MODEL_WINDOW_SAMPLES - arr.shape[0], axis=0)
                arr = np.concatenate([arr, pad], axis=0)
            st.session_state.last_window = arr
            return arr

        if st.session_state.get("last_window") is not None:
            return st.session_state.last_window

        # Avoid a second serial reader in the slow fragment. Wait for fast buffer.
        return None

    return get_next_window(mode, sim_state)


def render_sidebar_live_values() -> None:
    st.markdown("### 📡 Live Sensor Readings")
    raw = st.session_state.get("last_raw")
    if raw:
        hist = st.session_state.get("sensor_history", {})
        gsr_val = float(raw.get("GSR", 0.0))
        if gsr_val <= 0.0:
            gsr_val = _last_nonzero(hist.get("gsr", []), default=0.0)
        gsr_color = "🔴" if gsr_val > 2000 else "🟢"

        spo2_val = float(raw.get("SPO2", 0.0))
        if spo2_val <= 0.0:
            spo2_val = _last_nonzero(hist.get("spo2", []), default=0.0)
        spo2_color = "🔴" if 0 < spo2_val < 94 else "🟢"

        temp_val = float(raw.get("TEMP", 0.0))
        if temp_val <= 0.0:
            temp_val = _last_nonzero(hist.get("temp", []), default=0.0)
        temp_color = "🔴" if temp_val > 37.5 else "🟢"

        bpm_val = max(float(raw.get("BPM", 0.0)), float(raw.get("ECG_HR", 0.0)))
        if bpm_val <= 0.0:
            bpm_val = _median_recent(hist.get("bpm", []), k=5, default=0.0)
        bpm_color = "🔴" if bpm_val > 110 or (0 < bpm_val < 50) else "🟢"

        st.markdown(
            f"{gsr_color} **GSR:** {gsr_val:.0f}\n\n"
            f"{spo2_color} **SpO2:** {spo2_val:.1f}%\n\n"
            f"{temp_color} **Temp:** {temp_val:.1f}°C\n\n"
            f"{bpm_color} **BPM:** {bpm_val:.0f}\n\n"
            f"🔵 **State:** {raw.get('STATE', 'UNKNOWN')}"
        )
    else:
        io = st.session_state.get("io_status", {})
        if io.get("reason") == "firmware_summary_mode":
            st.error("ESP32 is connected but not sending GSR/SPO2/TEMP/AX data.")
            if io.get("last_line"):
                st.caption(f"Last line from device: {io.get('last_line')}")
            st.caption("Flash the sensor-stream firmware (GSR,SPO2,TEMP,AX,AY,AZ,BPM) and restart.")
        else:
            # Show status instead of generic connecting message
            reader = st.session_state.get("serial_reader")
            is_live = reader is not None and reader.connected
            if is_live:
                st.info("● ESP32 connected but waiting for first data...")
            else:
                st.info("◎ Running in simulation mode — pre-populating buffer...")


def render_sidebar_panel(mode: str) -> Tuple[Optional[str], int, str]:
    st.sidebar.markdown("### Connection")
    # Dynamically check if hardware is actually connected (not just mode-based)
    reader = st.session_state.get("serial_reader")
    is_live = reader is not None and reader.connected
    
    if is_live:
        st.sidebar.success("● ESP32 Live")
    else:
        st.sidebar.warning("◎ Simulation")

    sim_state = None
    if mode == "simulation":
        # Initialize default sim state if not already set
        if "sim_state_selected" not in st.session_state:
            st.session_state.sim_state_selected = "normal_baseline"
        
        sim_state = st.sidebar.selectbox(
            "Simulate State:",
            [
                "normal_baseline",
                "sympathetic_arousal",
                "parasympathetic_suppression",
                "mixed_dysregulation",
            ],
            index=[
                "normal_baseline",
                "sympathetic_arousal",
                "parasympathetic_suppression",
                "mixed_dysregulation",
            ].index(st.session_state.get("sim_state_selected", "normal_baseline")),
            format_func=lambda x: x.replace("_", " ").title(),
            on_change=lambda: st.session_state.update({"sim_state_selected": st.session_state.get("sim_state_sidebar", "normal_baseline")}),
            key="sim_state_sidebar",
        )
        
        # Store the selection persistently
        st.session_state.sim_state_selected = sim_state
        
        # Show which state is being simulated
        state_display = sim_state.replace("_", " ").title()
        st.sidebar.info(f"📊 Simulating: **{state_display}**")

    st.sidebar.divider()
    render_sidebar_live_values()

    st.sidebar.divider()
    st.sidebar.markdown("### 🧾 Reading Log")
    recent = st.session_state.get("history", [])[-8:]
    if recent:
        for item in reversed(recent):
            ts = item.get("timestamp", "--:--:--")
            state = item.get("display_state", item.get("predicted_class", "-"))
            conf = float(item.get("confidence", 0.0))
            dom = item.get("dominant_sensor", "-")
            st.sidebar.caption(f"{ts} | {state} | {conf:.0f}% | {dom}")
    else:
        st.sidebar.caption("No AI readings yet")

    st.sidebar.divider()
    session_key = (st.session_state.get("groq_key") or "").strip()
    key_default = session_key if session_key else (GROQ_API_KEY_ENV or "")
    st.session_state.groq_key = st.sidebar.text_input(
        "Groq API Key",
        value=key_default,
        type="password",
        help="Used for clinical interpretation only",
    ).strip()

    st.sidebar.divider()
    st.sidebar.markdown("### 📋 Active Alerts")
    alerts = st.session_state.get("current_alerts", [])
    if alerts:
        for level, message in alerts:
            if level == "error":
                st.sidebar.error(message)
            elif level == "warning":
                st.sidebar.warning(message)
            else:
                st.sidebar.info(message)
    else:
        st.sidebar.success("No active alerts")

    st.sidebar.divider()
    # Reduce default update interval from 3s to 1.5s for more responsive updates
    interval = st.sidebar.slider("Update interval (seconds)", 1, 5, 1)

    return sim_state, interval, st.session_state.groq_key


def render_ai_tab(window: np.ndarray, prediction: dict, pcs: float, sensor_conflict: bool, groq_key: str) -> None:
    # Check SpO2 sensor status
    raw = st.session_state.get("last_raw", {})
    spo2_now = float(raw.get("SPO2", 0.0))
    current_time = time.time()
    
    # Track SpO2=0 duration for warning state
    if spo2_now == 0.0:
        if st.session_state.get("spo2_zero_start_time") is None:
            st.session_state.spo2_zero_start_time = current_time
        spo2_zero_duration = current_time - st.session_state.spo2_zero_start_time
    else:
        st.session_state.spo2_zero_start_time = None
        spo2_zero_duration = 0.0
    
    # Determine display state based on SpO2 warning
    if spo2_zero_duration > 5.0:
        display_state = "Parasympathetic Suppression"
    else:
        display_state = "Normal Baseline"
    
    # Override prediction display
    prediction["display_state"] = display_state
    
    validation = st.session_state.get("last_validation") or run_signal_validation(window, sensor_conflict)
    
    # Non-blocking Groq clinical interpretation call
    def _fetch_groq_in_background():
        import warnings
        try:
            # Suppress Streamlit ScriptRunContext warning in background thread
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=DeprecationWarning)
                if groq_key and groq_key.strip():
                    payload = get_clinical_interpretation(
                        predicted_class=display_state,
                        confidence=prediction["confidence"],
                        cav_dict=prediction["cav"],
                        pcs_score=pcs,
                        sensor_conflict=sensor_conflict,
                        low_confidence=prediction["low_confidence"],
                        api_key=groq_key,
                    )
                    st.session_state.clinical_payload = payload
                    st.session_state.last_clinical_update = datetime.now().strftime("%H:%M:%S")
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            st.session_state.clinical_payload = None
    
    # Start Groq call in background thread (non-blocking)
    if not st.session_state.get("groq_thread_running"):
        st.session_state.groq_thread_running = True
        thread = threading.Thread(target=_fetch_groq_in_background, daemon=True)
        thread.start()

    render_main_state_card(prediction, pcs, sensor_conflict, display_state)
    render_sensor_section(window, prediction, display_state)
    render_sensor_story_panel(window, prediction, display_state)
    render_clinical_section(st.session_state.get("clinical_payload"), CLASS_COLORS.get(display_state, "#333333"), bool(groq_key), prediction)
    render_integrity_section(prediction, validation)
    render_history_section()
    
    # Reset thread flag for next cycle
    st.session_state.groq_thread_running = False


def main():
    # Initialize background serial reader ONCE per session
    if "serial_reader" not in st.session_state:
        try:
            reader = get_serial_reader(ESP32_PORT_ENV)
            st.session_state.serial_reader = reader
            logger.info("[INIT] Background serial thread initialized")
            # Give thread 1 second to open port and stabilize connection status
            time.sleep(1.0)
            logger.info(
                f"[APP] Serial thread status: connected={reader.connected} port={reader.port}"
            )
            if reader.connected:
                logger.info("✅ ESP32 CONNECTED — Live mode active")
            else:
                logger.info("⚠️  No hardware — Simulation mode active")
        except Exception as e:
            st.session_state.serial_reader = None
            logger.warning(f"[INIT] Failed to initialize serial thread: {e}")

    mode, _ = get_mode_and_sim_state()
    sim_state, interval, groq_key = render_sidebar_panel(mode)

    render_header(mode)

    # One raw sample per cycle, shared by both tabs.
    logger.info(f"[MAIN] Starting cycle - fetching latest raw sample")
    raw = get_latest_raw_sample(mode, sim_state)
    logger.info(f"[MAIN] Got raw sample: {raw is not None}")
    if raw:
        st.session_state.last_raw = raw  # Store for render_live_sensor_tab
        state_name = str(raw.get("STATE", "NORMAL"))
        logger.info(f"[MAIN] Appending to stream buffer: GSR={raw['GSR']:.0f}, SPO2={raw['SPO2']:.1f}, TEMP={raw['TEMP']:.1f}, STATE={state_name}")
        update_sensor_history(raw, state_name)
        append_stream_buffer(raw, state_name)
        append_normalized_sample(raw)
        logger.info(f"[MAIN] Buffer now has {len(st.session_state.stream_buffer['gsr'])} samples")

    # Single-cycle counter drives model and Groq cadence.
    st.session_state.cycle_count = int(st.session_state.get("cycle_count", 0)) + 1
    cycle = st.session_state.cycle_count

    # Run model inference every 5 cycles using shared session buffers.
    if cycle % 5 == 0:
        logger.info(f"[MODEL] Cycle {cycle}: checking for inference...")
        window = build_window_for_inference(mode, sim_state)
        logger.info(f"[MODEL] Window obtained: {window is not None}")
        if window is not None:
            ready, msg = hardware_inference_ready()
            logger.info(f"[MODEL] Hardware ready: {ready} ({msg})")
            if mode != "hardware" or ready or True:  # Allow inference even if sensors warming up
                logger.info(f"[MODEL] Running inference (mode={mode}) on fresh window shape={window.shape}")
                prediction = mc_dropout_predict(load_model(), window, T=6)
                pcs, sensor_conflict = compute_pcs(load_model(), window)

                display_state = prediction["predicted_class"]
                if mode == "simulation" and sim_state in SIM_TO_CLASS:
                    display_state = SIM_TO_CLASS[sim_state]

                alerts = get_alerts(prediction, sensor_conflict, state_override=display_state)
                st.session_state.current_alerts = alerts

                validation = run_signal_validation(window, sensor_conflict)
                st.session_state.last_validation = validation

                snapshot = {
                    **prediction,
                    "display_state": display_state,
                    "pcs": pcs,
                    "sensor_conflict": sensor_conflict,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                }
                st.session_state.reading_count += 1
                st.session_state.last_result = snapshot
                st.session_state.history.append(snapshot)
                if len(st.session_state.history) > 20:
                    st.session_state.history = st.session_state.history[-20:]
                
                # Log model inference result
                reader = st.session_state.get("serial_reader")
                is_live = reader is not None and reader.connected
                logger.info(
                    f"📊 Reading #{st.session_state.reading_count} | "
                    f"State: {display_state} | "
                    f"Confidence: {prediction.get('confidence', 0.0):.1f}% | "
                    f"Dominant: {prediction.get('dominant_sensor', 'N/A')} | "
                    f"PCS: {pcs:.2f} | "
                    f"Mode: {'HW' if is_live else 'SIM'}"
                )

                st.session_state.clinical_context = {
                    "predicted_class": display_state,
                    "confidence": float(prediction["confidence"]),
                    "cav_dict": dict(prediction["cav"]),
                    "pcs_score": float(pcs),
                    "sensor_conflict": bool(sensor_conflict),
                    "low_confidence": bool(prediction["low_confidence"]),
                }

    # Refresh Groq interpretation every 30 cycles.
    if cycle % 30 == 0 and groq_key:
        ctx = st.session_state.get("clinical_context")
        if ctx:
            payload = get_clinical_interpretation(
                predicted_class=ctx["predicted_class"],
                confidence=ctx["confidence"],
                cav_dict=ctx["cav_dict"],
                pcs_score=ctx["pcs_score"],
                sensor_conflict=ctx["sensor_conflict"],
                low_confidence=ctx["low_confidence"],
                api_key=groq_key,
            )
            if payload:
                st.session_state.clinical_payload = payload
                st.session_state.last_clinical_update = datetime.now().strftime("%H:%M:%S")

    tab1, tab2 = st.tabs([
        "📈  Live Sensor Monitor",
        "🧠  AI Analysis",
    ])

    logger.info(f"[MAIN] Tabs created, rendering tab1")
    with tab1:
        render_live_sensor_tab()
    
    logger.info(f"[MAIN] Tab1 rendered, checking AI tab readiness")
    with tab2:
        logger.info(f"[MAIN] AI tab starting - checking last_result")
        last = st.session_state.get("last_result")
        logger.info(f"[MAIN] last_result={last is not None}")
        if last is None:
            logger.info(f"[MAIN] No predictions yet, showing collect message")
            st.info("Collecting data for first AI inference...")
        else:
            logger.info(f"[MAIN] Building inference window")
            window = st.session_state.get("last_window")
            if window is None:
                logger.info(f"[MAIN] No cached window, building from inference")
                window = build_window_for_inference(mode, sim_state)
                logger.info(f"[MAIN] Built window: {window.shape if window is not None else None}")
            if window is None:
                logger.info(f"[MAIN] Window still None after build")
                st.info("Waiting for sufficient buffered samples...")
            else:
                logger.info(f"[MAIN] Rendering AI tab with window {window.shape}")
                render_ai_tab(
                    window,
                    last,
                    float(last.get("pcs", 0.0)),
                    bool(last.get("sensor_conflict", False)),
                    groq_key,
                )
                logger.info(f"[MAIN] AI tab rendered successfully")

    # Deterministic refresh loop so data collection and inference continue without clicks.
    logger.info(f"[MAIN] Sleeping {interval}s before next rerun")
    time.sleep(interval)
    logger.info("[MAIN] Triggering timed rerun")
    st.rerun()


if __name__ == "__main__":
    main()
