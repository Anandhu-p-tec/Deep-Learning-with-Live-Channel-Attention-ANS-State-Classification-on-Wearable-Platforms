"""Groq API integration for clinical ANS interpretation."""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from groq import Groq


def get_clinical_interpretation(
    predicted_class: str,
    confidence: float,
    cav_dict: dict,
    pcs_score: float,
    sensor_conflict: bool,
    low_confidence: bool,
    api_key: Optional[str],
) -> Optional[Dict[str, str]]:
    """
    Get clinical interpretation of ANS classification using Groq LLM.

    Args:
        predicted_class: ANS state classification
        confidence: Model confidence percentage (0-100)
        cav_dict: Channel attention vector (dict with sensor weights)
        pcs_score: Per-channel similarity score
        sensor_conflict: Whether sensor conflict detected
        low_confidence: Low confidence flag
        api_key: Groq API key

    Returns:
        Dict with interpretation fields, or None if unavailable.
        Never raises exceptions.
    """
    try:
        # Return None silently if no API key
        if not api_key or not isinstance(api_key, str) or api_key.strip() == "":
            return None

        # Initialize Groq client
        client = Groq(api_key=api_key.strip())

        # System prompt
        system_prompt = (
            "You are a clinical AI assistant interpreting autonomic nervous "
            "system monitoring data from a wearable sensor device. You provide "
            "brief, accurate, plain-English clinical interpretations of ANS "
            "state classifications. You never diagnose. You always recommend "
            "physician review for any anomalous findings. Respond ONLY with "
            "valid JSON matching this exact structure and no other text: "
            "{\"interpretation\":\"...\",\"what_to_watch\":\"...\","
            "\"caregiver_action\":\"...\",\"urgency\":\"routine|monitor|alert\"}."
        )

        # Determine dominant sensor
        dominant_sensor = max(cav_dict, key=cav_dict.get) if cav_dict else "Unknown"

        # Build user message
        user_message = (
            f"ANS Classification Result:\n"
            f"- Detected State: {predicted_class}\n"
            f"- Model Confidence: {confidence}%\n"
            f"- Sensor Attribution (PAST): GSR {cav_dict.get('GSR', 0)*100:.0f}%, "
            f"SpO2 {cav_dict.get('SpO2', 0)*100:.0f}%, "
            f"Temp {cav_dict.get('Temp', 0)*100:.0f}%, "
            f"Accel {cav_dict.get('Accel', 0)*100:.0f}%\n"
            f"- Dominant Sensor: {dominant_sensor}\n"
            f"- Physiological Coherence Score: {pcs_score}\n"
            f"- Sensor Conflict Detected: {sensor_conflict}\n"
            f"- Low Confidence Flag: {low_confidence}\n\n"
            "Return JSON where:\n"
            "- interpretation: 2-3 sentence clinical interpretation\n"
            "- what_to_watch: one sentence on what physiological sign to watch next\n"
            "- caregiver_action: one sentence for a non-medical caregiver right now\n"
            "- urgency: one of routine, monitor, alert"
        )

        # Call Groq API
        def _request_json(force_format: bool, model_name: str):
            kwargs = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 220,
                "temperature": 0.3,
            }
            if force_format:
                kwargs["response_format"] = {"type": "json_object"}
            return client.chat.completions.create(**kwargs)

        def _parse_payload(text: str):
            try:
                return json.loads(text)
            except Exception:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(text[start : end + 1])
                raise

        configured_model = os.getenv("GROQ_MODEL", "").strip()
        model_candidates = [
            m
            for m in [
                configured_model,
                "llama-3.1-8b-instant",
                "llama-3.3-70b-versatile",
                "llama3-8b-8192",
            ]
            if m
        ]

        message = None
        last_error = None
        for model_name in model_candidates:
            try:
                message = _request_json(force_format=True, model_name=model_name)
                break
            except Exception as exc:
                last_error = exc
                try:
                    message = _request_json(force_format=False, model_name=model_name)
                    break
                except Exception as exc2:
                    last_error = exc2
                    continue

        if message is None:
            reason = str(last_error) if last_error else "Groq request failed"
            short_reason = reason[:180]
            return {
                "interpretation": (
                    "Clinical interpretation is temporarily unavailable from Groq. "
                    f"Reason: {short_reason}."
                ),
                "what_to_watch": "Continue monitoring confidence and sensor coherence trend.",
                "caregiver_action": "Retry shortly, or set GROQ_MODEL in .env to a currently supported model.",
                "urgency": "monitor",
            }

        # Extract response
        response_text = message.choices[0].message.content
        if not response_text:
            return None

        payload = _parse_payload(response_text)
        required_keys = [
            "interpretation",
            "what_to_watch",
            "caregiver_action",
            "urgency",
        ]
        if not all(k in payload for k in required_keys):
            return None

        urgency = str(payload.get("urgency", "")).strip().lower()
        if urgency not in {"routine", "monitor", "alert"}:
            urgency = "monitor"

        cleaned = {
            "interpretation": str(payload.get("interpretation", "")).strip(),
            "what_to_watch": str(payload.get("what_to_watch", "")).strip(),
            "caregiver_action": str(payload.get("caregiver_action", "")).strip(),
            "urgency": urgency,
        }
        if not all(cleaned.values()):
            return None
        return cleaned

    except Exception:
        # Silently return None on any error
        return None
