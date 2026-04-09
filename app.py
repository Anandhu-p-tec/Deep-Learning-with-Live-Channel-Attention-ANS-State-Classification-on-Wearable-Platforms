"""ANS State Classification - Clinical Narrative UI."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

# Session state defaults must be initialized at the top.
defaults = {
    "history": [],
    "groq_key": "",
    "last_result": None,
    "last_validation": None,
    "reading_count": 0,
    "mode": "auto",
    "current_alerts": [],
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
    load_or_create_model,
    mc_dropout_predict,
    compute_pcs,
)
from serial_reader.esp32_reader import ESP32Reader, has_device
from serial_reader.simulator import get_simulated_window
from groq_interpreter import get_clinical_interpretation

load_dotenv()
GROQ_API_KEY_ENV = os.getenv("GROQ_API_KEY", "")

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


def get_mode_and_sim_state() -> Tuple[str, Optional[str]]:
    if st.session_state.mode == "auto":
        st.session_state.mode = "hardware" if has_device() else "simulation"

    mode = st.session_state.mode
    return mode, None


def get_next_window(mode: str, sim_state: Optional[str]) -> Optional[np.ndarray]:
    try:
        if mode == "hardware":
            reader = ESP32Reader()
            window = reader.read_window(n_samples=500)
            reader.close()
            if window is None:
                st.session_state.mode = "simulation"
                return get_simulated_window("normal_baseline", n_samples=500)
            return window
        return get_simulated_window(sim_state or "normal_baseline", n_samples=500)
    except Exception:
        return None


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

    checks = [
        ("Flatline Detection", bool(np.all(stds > 0.002)), "All channels active"),
        ("Artifact Removal", bool(max_spike < 0.45), "No spikes detected"),
        (
            "Range Validation",
            bool(np.min(window) >= 0.0 and np.max(window) <= 1.0),
            "All values in range",
        ),
        ("Noise Analysis", bool(float(np.mean(stds)) < 0.22), "Signal clean"),
        ("Cross-channel", bool(not sensor_conflict), "Physiologically coherent"),
        (
            "Data Integrity",
            bool(window.shape == (500, 4) and np.isfinite(window).all()),
            "No missing samples",
        ),
    ]

    score = int(round(100.0 * sum(1 for _, ok, _ in checks if ok) / len(checks)))
    if score >= 90:
        quality_label = "Excellent"
    elif score >= 75:
        quality_label = "Good"
    elif score >= 60:
        quality_label = "Moderate"
    else:
        quality_label = "Needs Review"

    channel_quality = {
        "GSR": float(max(0.0, min(1.0, 1.0 - stds[0] * 2.2))),
        "SpO2": float(max(0.0, min(1.0, 1.0 - stds[1] * 2.2))),
        "Temp": float(max(0.0, min(1.0, 1.0 - stds[2] * 2.2))),
        "Accel": float(max(0.0, min(1.0, 1.0 - stds[3] * 2.2))),
    }

    return {
        "checks": checks,
        "score": score,
        "label": quality_label,
        "channel_quality": channel_quality,
    }


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
                st.markdown(f"<div style='font-weight:700;color:#111827;'>{icon} {label}</div>", unsafe_allow_html=True)
                st.markdown("<div style='margin-top:10px;font-size:0.85rem;color:#6b7280;'>Current signal level</div>", unsafe_allow_html=True)
                st.progress(float(val["norm"]))
                st.markdown(f"<div style='font-size:0.95rem;color:#111827;margin-top:4px;'>{val['label']}</div>", unsafe_allow_html=True)
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
    st.caption("Generated by Llama 3 • Not a medical diagnosis - For monitoring guidance only")

    if not has_key or clinical_payload is None:
        st.markdown(
            "<div style='background:#f3f4f6;border:1px solid #d1d5db;border-radius:10px;padding:16px;color:#4b5563;'>"
            "Clinical interpretation unavailable — add Groq API key in sidebar to enable"
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
    st.subheader("Signal Integrity Verification")
    c_left, c_right = st.columns([1, 1])

    with c_left:
        st.markdown("<div style='font-weight:600;margin-bottom:8px;'>Sensor Attribution vs Signal Quality</div>", unsafe_allow_html=True)
        fig = build_radar_chart(prediction, validation)
        st.plotly_chart(fig, width="stretch")

    with c_right:
        checks = validation["checks"]
        for name, ok, note in checks:
            icon = "✓" if ok else "⚠"
            color = "#1D9E75" if ok else "#C0392B"
            status_text = note if ok else f"Issue: {note}"
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;border-bottom:1px solid #e5e7eb;padding:7px 2px;'>"
                f"<div><span style='color:{color};font-weight:700;margin-right:8px;'>{icon}</span>{name}</div>"
                f"<div style='color:{color};font-weight:600;'>{status_text}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            f"<div style='margin-top:14px;font-size:1.1rem;font-weight:700;'>Signal Quality: {validation['score']}/100 — {validation['label']}</div>",
            unsafe_allow_html=True,
        )


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


def render_sidebar(mode: str, alerts: List[Tuple[str, str]]) -> Tuple[Optional[str], int, str]:
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

    interval = st.sidebar.slider("Update interval (seconds)", 1, 10, 3)
    st.sidebar.button("Refresh reading", type="primary", width="stretch")
    st.sidebar.caption("Manual refresh keeps the screen stable and avoids flashing.")

    st.sidebar.divider()
    st.sidebar.markdown("### 🔑 Groq API Key")
    key_input = st.sidebar.text_input(
        "Groq API Key",
        type="password",
        placeholder="Paste API key",
        label_visibility="collapsed",
    )
    st.sidebar.caption("Get free key at console.groq.com")

    if key_input:
        st.session_state.groq_key = key_input.strip()
    elif not st.session_state.groq_key and GROQ_API_KEY_ENV:
        st.session_state.groq_key = GROQ_API_KEY_ENV.strip()

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

    return sim_state, interval, st.session_state.groq_key


def main():
    mode, _ = get_mode_and_sim_state()

    sim_state, interval, groq_key = render_sidebar(mode, st.session_state.current_alerts)

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

    st.caption(f"Refresh manually using the sidebar button. Suggested interval: {interval}s")


if __name__ == "__main__":
    main()
