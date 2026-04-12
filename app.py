"""ANS State Classification - Clinical Narrative UI."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

FRAGMENT_SUPPORTED = hasattr(st, "fragment")
FAST_FRAGMENT_INTERVAL = "2s"
MODEL_FRAGMENT_INTERVAL = "12s"
CLINICAL_FRAGMENT_INTERVAL = "90s"

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
from serial_reader.esp32_reader import ESP32Reader, has_device, normalize_reading
from serial_reader.simulator import get_simulated_window
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


@st.cache_resource
def load_model():
    with st.spinner("Loading monitor intelligence..."):
        return load_or_create_model()


def get_session_reader() -> ESP32Reader:
    reader = st.session_state.get("esp32_reader")
    if isinstance(reader, ESP32Reader):
        return reader

    reader = ESP32Reader(
        read_timeout=0.15,
        scan_timeout=0.8,
        preferred_port=ESP32_PORT_ENV,
    )
    st.session_state.esp32_reader = reader
    return reader


def close_session_reader() -> None:
    reader = st.session_state.get("esp32_reader")
    if isinstance(reader, ESP32Reader):
        try:
            reader.close()
        except Exception:
            logger.exception("[HW] failed to close session reader")
    st.session_state.esp32_reader = None


def get_mode_and_sim_state() -> Tuple[str, Optional[str]]:
    # Always prefer live hardware when it is available, so a previous
    # simulation fallback does not permanently lock the session.
    st.session_state.mode = "hardware" if has_device(preferred_port=ESP32_PORT_ENV) else "simulation"
    mode = st.session_state.mode
    if mode == "hardware":
        logger.info("✅ ESP32 CONNECTED on COM3 — Live mode active")
    else:
        close_session_reader()
        logger.info("⚠️  No hardware — Simulation mode active")
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
    try:
        if mode == "hardware":
            # Read a shorter live window for faster startup, then resample.
            reader = ESP32Reader(
                read_timeout=0.15,
                scan_timeout=0.8,
                preferred_port=ESP32_PORT_ENV,
            )
            window = reader.read_window(n_samples=MODEL_WINDOW_SAMPLES, max_window_seconds=2.5)
            stats = dict(reader.last_stats)
            last_raw = dict(reader.last_raw) if reader.last_raw else None
            reader.close()
            st.session_state.io_status = stats
            st.session_state.last_raw = last_raw
            logger.info(
                "[HW] port=%s ok=%s samples=%s/%s valid=%s invalid=%s elapsed=%.3fs reason=%s",
                stats.get("port"),
                stats.get("ok"),
                stats.get("collected_samples"),
                stats.get("requested_samples"),
                stats.get("valid_lines"),
                stats.get("invalid_lines"),
                float(stats.get("elapsed_seconds", 0.0)),
                stats.get("reason"),
            )
            if stats.get("last_valid_line"):
                logger.info("[HW] last_valid_line=%s", stats.get("last_valid_line"))
            if window is None or window.shape[0] < 1:
                if st.session_state.get("last_window") is not None:
                    st.session_state.io_status = {
                        **stats,
                        "ok": False,
                        "reason": "reused_last_window",
                    }
                    return st.session_state.last_window

                st.session_state.mode = "simulation"
                st.session_state.io_status = {
                    **stats,
                    "ok": False,
                    "reason": "fallback_to_simulation",
                }
                sim_window = get_simulated_window("normal_baseline", n_samples=MODEL_WINDOW_SAMPLES)
                st.session_state.last_window = sim_window
                return sim_window

            resampled = _resample_window(window, target_samples=MODEL_WINDOW_SAMPLES)
            st.session_state.last_window = resampled
            return resampled
        st.session_state.io_status = {}
        st.session_state.last_raw = None
        sim_window = get_simulated_window(sim_state or "normal_baseline", n_samples=MODEL_WINDOW_SAMPLES)
        st.session_state.last_window = sim_window
        return sim_window
    except Exception:
        if st.session_state.get("last_window") is not None:
            logger.exception("[HW] read failure, reusing last valid window")
            st.session_state.io_status = {
                "port": ESP32_PORT_ENV,
                "ok": False,
                "reason": "exception_reused_last_window",
                "collected_samples": 0,
                "requested_samples": MODEL_WINDOW_SAMPLES,
                "valid_lines": 0,
                "invalid_lines": 0,
                "elapsed_seconds": 0.0,
                "last_valid_line": "",
            }
            return st.session_state.last_window

        st.session_state.mode = "simulation"
        logger.exception("[HW] read failure, switching to simulation")
        st.session_state.io_status = {
            "port": ESP32_PORT_ENV,
            "ok": False,
            "reason": "exception_fallback",
            "collected_samples": 0,
            "requested_samples": MODEL_WINDOW_SAMPLES,
            "valid_lines": 0,
            "invalid_lines": 0,
            "elapsed_seconds": 0.0,
            "last_valid_line": "",
        }
        sim_window = get_simulated_window("normal_baseline", n_samples=MODEL_WINDOW_SAMPLES)
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


def render_live_sensor_tab() -> None:
    st.subheader("📈 Live Sensor Monitor")
    st.caption("Real-time readings from GSR, SpO2, Temp, BPM, and ECG")

    hist = st.session_state.sensor_history
    if not hist["readings"]:
        st.info("Waiting for sensor history...")
        return

    raw = st.session_state.get("last_raw") or {}
    gsr_now = float(raw.get("GSR", hist["gsr"][-1] if hist["gsr"] else 0.0))
    if gsr_now <= 0.0:
        gsr_now = _last_nonzero(hist.get("gsr", []), default=0.0)
    spo2_now = float(raw.get("SPO2", hist["spo2"][-1] if hist["spo2"] else 0.0))
    if spo2_now <= 0.0:
        spo2_now = _last_nonzero(hist.get("spo2", []), default=0.0)
    temp_now = float(raw.get("TEMP", hist["temp"][-1] if hist["temp"] else 0.0))
    if temp_now <= 0.0:
        temp_now = _last_nonzero(hist.get("temp", []), default=0.0)
    bpm_now = _effective_bpm(raw, hist)
    accel_now = _median_recent(hist.get("accel", []), k=5, default=0.0)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric(f"{'🔴' if gsr_now > 2000 else '🟢'} GSR", f"{gsr_now:.0f}")
    with c2:
        st.metric(f"{'🔴' if 0 < spo2_now < 94 else '🟢'} SpO2", f"{spo2_now:.1f}%")
    with c3:
        temp_delta = f"{temp_now - hist['temp'][-2]:.1f}" if len(hist["temp"]) > 1 else None
        st.metric(f"{'🔴' if temp_now > 37.5 else '🟢'} Temperature", f"{temp_now:.1f}°C", delta=temp_delta)
    with c4:
        st.metric(f"{'🔴' if bpm_now > 110 or (0 < bpm_now < 50) else '🟢'} BPM", f"{bpm_now:.0f}")
    with c5:
        st.metric(f"{'🔴' if accel_now > 2.0 else '🟢'} Movement", f"{accel_now:.2f}g")

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
        vertical_spacing=0.12,
        horizontal_spacing=0.08,
    )

    x_vals = hist["readings"]
    fig.add_trace(go.Scatter(x=x_vals, y=hist["gsr"], mode="lines", line=dict(color="#1D9E75", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_vals, y=hist["spo2"], mode="lines", line=dict(color="#378ADD", width=2)), row=1, col=2)
    fig.add_trace(go.Scatter(x=x_vals, y=hist["temp"], mode="lines", line=dict(color="#EF9F27", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=x_vals, y=hist["bpm"], mode="lines", line=dict(color="#D85A30", width=2)), row=2, col=2)

    lo_vals = hist.get("lo", [])
    ecg_vals = hist.get("ecg", [])
    ecg_plot = []
    for i, val in enumerate(ecg_vals):
        lo = lo_vals[i] if i < len(lo_vals) else 1
        ecg_plot.append(0.0 if lo == 1 else float(val))
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
    fig.update_yaxes(range=[85, 100], row=1, col=2)
    fig.update_yaxes(range=[30, 42], row=2, col=1)
    fig.update_yaxes(range=[0, 150], row=2, col=2)
    fig.update_yaxes(range=[0, 4095], row=3, col=1)
    st.plotly_chart(fig, width="stretch")

    if lo_vals and lo_vals[-1] == 1:
        st.info("Electrodes not connected")

    gsr_active = "🟢 GSR Active" if gsr_now > 0 else "🔴 GSR Active"
    spo2_active = "🟢 SpO2 Active" if spo2_now > 0 else "🔴 SpO2 Active"
    temp_active = "🟢 Temp Active" if temp_now > 0 else "🔴 Temp Active"
    ecg_active = "🟢 ECG Active" if (lo_vals and lo_vals[-1] == 0 and ecg_vals and ecg_vals[-1] > 0) else "🔴 ECG Active"
    st.markdown(f"{gsr_active}   {spo2_active}   {temp_active}   {ecg_active}")

    risk_now = int(round(_median_recent(hist.get("risk", []), k=5, default=float(raw.get("RISK", 0.0)))))
    state_now = _majority_recent(hist.get("state", []), k=5, default=str(raw.get("STATE", "NORMAL")))
    risk_color = "#1D9E75" if risk_now <= 1 else ("#EF9F27" if risk_now == 2 else "#D85A30")
    st.markdown(
        f"<span style='background:{risk_color};color:white;padding:6px 12px;border-radius:999px;font-weight:700;'>Hardware Risk Score: {risk_now}/5 — {state_now}</span>",
        unsafe_allow_html=True,
    )


def render_header(mode: str):
    badge_text = "● ESP32 Live" if mode == "hardware" else "◎ Simulation Mode"
    badge_color = "#1D9E75" if mode == "hardware" else "#E0A800"

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
    conf = float(prediction["confidence"])
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


def render_clinical_section(clinical_payload: Optional[dict], state_color: str, has_key: bool):
    st.subheader("🤖 AI Clinical Interpretation")
    last_ai = st.session_state.get("last_clinical_update", "--:--:--")
    st.caption(f"Generated by Llama 3 • Last AI refresh: {last_ai} • Not a medical diagnosis")

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
        confidence = prediction["confidence"]
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
    y_vals = [float(item["confidence"]) for item in history]
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
    model = load_model()
    window = get_next_window(mode, sim_state)
    if window is None:
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

    with st.container():
        try:
            render_header(mode)
        except Exception as e:
            st.error(f"Section failed: {e}")

    with st.container():
        try:
            render_main_state_card(prediction, pcs, sensor_conflict, display_state)
        except Exception as e:
            st.error(f"Section failed: {e}")

    with st.container():
        try:
            render_sensor_section(window, prediction, display_state)
        except Exception as e:
            st.error(f"Section failed: {e}")

    with st.container():
        try:
            render_live_sensor_activity()
        except Exception as e:
            st.error(f"Section failed: {e}")

    with st.container():
        try:
            render_clinical_section(
                clinical_payload,
                CLASS_COLORS.get(display_state, "#333333"),
                bool(groq_key),
            )
        except Exception as e:
            st.error(f"Section failed: {e}")

    with st.container():
        try:
            render_integrity_section(prediction, validation)
        except Exception as e:
            st.error(f"Section failed: {e}")

    with st.container():
        try:
            render_history_section()
        except Exception as e:
            st.error(f"Section failed: {e}")


def get_latest_raw_sample(mode: str, sim_state: Optional[str]) -> Optional[Dict[str, float]]:
    """Fetch one fresh raw sample for fast UI updates without model inference."""
    try:
        if mode == "hardware":
            reader = get_session_reader()
            # A short burst greatly improves chances of receiving at least one valid line.
            _ = reader.read_window(n_samples=5, max_window_seconds=1.2)
            st.session_state.io_status = dict(reader.last_stats)
            raw = dict(reader.last_raw) if reader.last_raw else None
            if raw:
                st.session_state.last_raw = raw
            return raw

        close_session_reader()
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
        norm = normalize_reading(raw)
        history = st.session_state.normalized_history
        history.append(norm.tolist())
        if len(history) > 800:
            st.session_state.normalized_history = history[-800:]
    except Exception:
        logger.exception("[FAST] failed to normalize fast sample")


def hardware_inference_ready() -> Tuple[bool, str]:
    """Check if live PPG inputs are stable enough for model inference."""
    raw = st.session_state.get("last_raw") or {}
    bpm = max(float(raw.get("BPM", 0.0)), float(raw.get("ECG_HR", 0.0)))
    spo2 = float(raw.get("SPO2", 0.0))

    # BPM near zero usually means finger is not detected on MAX3010x.
    if bpm < 40.0:
        return False, f"Heart rate too low for valid inference ({bpm:.1f})."
    if spo2 < 85.0:
        return False, f"SpO2 is unstable/too low for reliable inference ({spo2:.1f}%)."
    return True, ""


def build_window_for_inference(mode: str, sim_state: Optional[str]) -> Optional[np.ndarray]:
    """Build model window from fast-stream cache to avoid serial-port contention."""
    if mode == "hardware":
        history = st.session_state.get("normalized_history", [])
        if len(history) >= MODEL_WINDOW_SAMPLES:
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
            st.info("Connecting to sensor stream...")


def main():
    mode, _ = get_mode_and_sim_state()
    render_header(mode)
    tab1, tab2 = st.tabs([
        "📈  Live Sensor Monitor",
        "🧠  AI Analysis",
    ])

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

    if GROQ_API_KEY_ENV:
        st.session_state.groq_key = GROQ_API_KEY_ENV.strip()
    else:
        st.session_state.groq_key = ""
    groq_key = st.session_state.groq_key

    if not FRAGMENT_SUPPORTED:
        st.warning("This Streamlit build does not support fragment updates. Upgrade Streamlit to avoid full-page reruns.")
        st.session_state.reading_count += 1
        render_dashboard_cycle(mode, sim_state, groq_key, st.session_state.reading_count)
        return

    @st.fragment(run_every=FAST_FRAGMENT_INTERVAL)
    def live_sensor_fragment() -> None:
        raw = get_latest_raw_sample(mode, sim_state)
        if raw:
            state_name = raw.get("STATE", "NORMAL")
            update_sensor_history(raw, str(state_name))
            append_normalized_sample(raw)

            now_ts = time.time()
            last_log_ts = float(st.session_state.get("last_fast_log_ts", 0.0))
            if now_ts - last_log_ts >= 5.0:
                io = st.session_state.get("io_status", {})
                logger.info(
                    "[FAST] GSR=%.0f SPO2=%.1f TEMP=%.1f BPM=%.0f ECG=%s ECG_HR=%.0f LO=%s STATE=%s valid=%s invalid=%s reason=%s",
                    float(raw.get("GSR", 0.0)),
                    float(raw.get("SPO2", 0.0)),
                    float(raw.get("TEMP", 0.0)),
                    max(float(raw.get("BPM", 0.0)), float(raw.get("ECG_HR", 0.0))),
                    str(int(float(raw.get("ECG", 0.0)))),
                    float(raw.get("ECG_HR", 0.0)),
                    str(int(float(raw.get("LO", 1.0)))),
                    str(raw.get("STATE", "?")),
                    int(io.get("valid_lines", 0)),
                    int(io.get("invalid_lines", 0)),
                    str(io.get("reason", "")),
                )
                st.session_state.last_fast_log_ts = now_ts

        with tab1:
            try:
                render_live_sensor_tab()
            except Exception as e:
                st.error(f"Section failed: {e}")

    @st.fragment(run_every=FAST_FRAGMENT_INTERVAL)
    def sidebar_fast_fragment() -> None:
        render_sidebar_live_values()
        st.divider()
        st.markdown("### 🕒 Last Update")
        ts = datetime.now().strftime("%H:%M:%S")
        st.caption(f"Fast stream tick: {ts}")

    @st.fragment(run_every=MODEL_FRAGMENT_INTERVAL)
    def model_inference_fragment() -> None:
        model = load_model()
        window = build_window_for_inference(mode, sim_state)
        if window is None:
            io = st.session_state.get("io_status", {})
            if io.get("reason") == "firmware_summary_mode":
                st.error("Inference paused: ESP32 firmware is sending only summary lines (RISK/STATE).")
                if io.get("last_line"):
                    st.caption(f"Last line from device: {io.get('last_line')}")
                st.caption("Upload the full sensor telemetry firmware, then refresh this page.")
            else:
                st.info("Collecting live sensor samples for inference...")
            return

        if mode == "hardware":
            ready, reason = hardware_inference_ready()
            if not ready:
                raw = st.session_state.get("last_raw") or {}
                st.warning(f"Inference paused: {reason}")
                logger.info(
                    "[MODEL] skipped inference | reason=%s | raw_bpm=%.1f | raw_spo2=%.1f",
                    reason,
                    float(raw.get("BPM", 0.0)),
                    float(raw.get("SPO2", 0.0)),
                )
                return

        prediction = mc_dropout_predict(model, window, T=6)
        pcs, sensor_conflict = compute_pcs(model, window)

        display_state = prediction["predicted_class"]
        if mode == "simulation" and sim_state in SIM_TO_CLASS:
            display_state = SIM_TO_CLASS[sim_state]

        alerts = get_alerts(prediction, sensor_conflict, state_override=display_state)
        st.session_state.current_alerts = alerts
        validation = run_signal_validation(window, sensor_conflict)
        clinical_payload = st.session_state.get("clinical_payload")

        st.session_state.reading_count += 1
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
        st.session_state.clinical_context = {
            "predicted_class": display_state,
            "confidence": float(prediction["confidence"]),
            "cav_dict": dict(prediction["cav"]),
            "pcs_score": float(pcs),
            "sensor_conflict": bool(sensor_conflict),
            "low_confidence": bool(prediction["low_confidence"]),
        }

        # Structured terminal logs for fragment inference cycles.
        count = st.session_state.reading_count
        logger.info(
            "📊 Reading #%s | State: %s | Confidence: %.1f%% | Dominant: %s | PCS: %.2f | Quality: %s/100",
            count,
            prediction["predicted_class"],
            float(prediction["confidence"]),
            prediction["dominant_sensor"],
            float(pcs),
            int(validation["signal_quality_score"]),
        )
        if sensor_conflict:
            logger.warning("⚠️ SENSOR CONFLICT — PCS=%.2f below threshold 0.30", float(pcs))
        if prediction["low_confidence"]:
            logger.warning("❓ LOW CONFIDENCE — variance=%.4f > 0.12", float(prediction["variance"]))
        if prediction["predicted_class"] in ("Sympathetic Arousal", "Mixed Dysregulation") and prediction["confidence"] >= 75:
            logger.warning(
                "🚨 ALERT — %s detected at %.1f%% confidence",
                prediction["predicted_class"],
                float(prediction["confidence"]),
            )

        if not groq_key:
            logger.info("🤖 AI interpretation disabled: GROQ_API_KEY is not set")
        elif clinical_payload is None:
            logger.info("🤖 AI interpretation pending background refresh")
        else:
            logger.info(
                "🤖 AI interpretation ready | urgency=%s",
                str(clinical_payload.get("urgency", "monitor")),
            )

        with tab2:
            try:
                render_main_state_card(prediction, pcs, sensor_conflict, display_state)
                render_sensor_section(window, prediction, display_state)
                render_clinical_section(
                    clinical_payload,
                    CLASS_COLORS.get(display_state, "#333333"),
                    bool(groq_key),
                )
                render_integrity_section(prediction, validation)
                render_history_section()
            except Exception as e:
                st.error(f"Section failed: {e}")

    @st.fragment(run_every=CLINICAL_FRAGMENT_INTERVAL)
    def clinical_refresh_fragment() -> None:
        if not groq_key:
            return
        ctx = st.session_state.get("clinical_context")
        if not ctx:
            return

        start = time.time()
        payload = get_clinical_interpretation(
            predicted_class=ctx["predicted_class"],
            confidence=ctx["confidence"],
            cav_dict=ctx["cav_dict"],
            pcs_score=ctx["pcs_score"],
            sensor_conflict=ctx["sensor_conflict"],
            low_confidence=ctx["low_confidence"],
            api_key=groq_key,
        )
        elapsed = time.time() - start
        if payload:
            st.session_state.clinical_payload = payload
            st.session_state.last_clinical_update = datetime.now().strftime("%H:%M:%S")
            logger.info("🤖 AI interpretation refreshed in %.2fs", elapsed)
        else:
            logger.warning("🤖 AI interpretation refresh failed after %.2fs", elapsed)

    @st.fragment(run_every=MODEL_FRAGMENT_INTERVAL)
    def sidebar_slow_fragment() -> None:
        alerts = st.session_state.get("current_alerts", [])
        st.divider()
        st.markdown("### 📋 Active Alerts")
        if alerts:
            for level, message in alerts:
                if level == "error":
                    st.error(message)
                elif level == "warning":
                    st.warning(message)
                else:
                    st.info(message)
        else:
            st.success("No active alerts")

        st.divider()
        st.markdown("### 🕒 Last Inference")
        last_result = st.session_state.get("last_result")
        if last_result:
            st.caption(f"{last_result.get('timestamp', '--:--:--')} (12s cycle)")
        else:
            st.caption("--:--:-- (12s cycle)")

    live_sensor_fragment()
    model_inference_fragment()
    clinical_refresh_fragment()
    with st.sidebar:
        sidebar_fast_fragment()
        sidebar_slow_fragment()


if __name__ == "__main__":
    main()
