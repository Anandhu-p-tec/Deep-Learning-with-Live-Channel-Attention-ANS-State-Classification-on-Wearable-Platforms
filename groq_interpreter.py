"""Groq API integration for clinical ANS interpretation."""

from __future__ import annotations

from typing import Optional

from groq import Groq


def get_clinical_interpretation(
    predicted_class: str,
    confidence: float,
    cav_dict: dict,
    pcs_score: float,
    sensor_conflict: bool,
    low_confidence: bool,
    api_key: Optional[str],
) -> Optional[str]:
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
        Clinical interpretation string, or None if unavailable.
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
            "physician review for any anomalous findings. Keep responses to "
            "2-3 sentences maximum."
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
            f"Provide a brief clinical interpretation of what this pattern "
            f"suggests and what a caregiver should monitor."
        )

        # Call Groq API
        message = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=150,
            temperature=0.3,
        )

        # Extract response
        response_text = message.choices[0].message.content
        return response_text if response_text else None

    except Exception:
        # Silently return None on any error
        return None
