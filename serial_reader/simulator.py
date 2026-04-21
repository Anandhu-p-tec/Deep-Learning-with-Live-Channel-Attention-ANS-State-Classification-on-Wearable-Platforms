"""Synthetic sensor simulator for ANS state dashboard."""

from __future__ import annotations

from typing import Dict

import numpy as np


# CALIBRATED HARDWARE BASELINES (from ESP32 actual measurements)
GSR_BASELINE = 1625.0       # Correct: midpoint of 500-2750 Ω range
GSR_STRESS_HIGH = 2750.0
GSR_STRESS_LOW = 500.0

SPO2_BASELINE = 90.5
SPO2_STRESS_HIGH = 93.0
SPO2_STRESS_LOW = 87.0

TEMP_BASELINE = 36.5        # Correct: normal body temp center
TEMP_STRESS_HIGH = 37.5
TEMP_STRESS_LOW = 36.0

# Backward compatibility
GSR_MIN, GSR_MAX = 0.0, 4095.0
SPO2_MIN, SPO2_MAX = 85.0, 100.0
TEMP_MIN, TEMP_MAX = 35.0, 40.0
ACCEL_AXIS_MIN, ACCEL_AXIS_MAX = -2.0, 2.0
ACCEL_MAG_MIN, ACCEL_MAG_MAX = 0.0, 20.0


# Updated MODE_CONFIG to use actual sensor baselines
MODE_CONFIG = {
	"normal_baseline": {
		"gsr": GSR_BASELINE,           # 1625 (normal: 500-2750)
		"spo2": SPO2_BASELINE,         # 90.5% (normal)
		"temp": TEMP_BASELINE,         # 36.5°C (normal: 36-37)
		"ax": 0.0,
		"ay": 0.0,
		"az": 0.0,
	},
	"sympathetic_arousal": {
		"gsr": 2200.0,                 # High stress GSR (elevated sweat)
		"spo2": 88.5,                  # Lower SpO2 (stress/breathing change)
		"temp": 37.5,                  # Elevated temp
		"ax": 0.15,
		"ay": 0.08,
		"az": 0.12,
	},
	"parasympathetic_suppression": {
		"gsr": 800.0,                  # Very low GSR (under-activated)
		"spo2": 85.5,                  # Low SpO2
		"temp": 35.5,                  # Low temp
		"ax": 0.0,
		"ay": 0.0,
		"az": 0.0,
	},
	"mixed_dysregulation": {
		"gsr": 2500.0,                 # High GSR (dysregulation)
		"spo2": 86.5,                  # Low SPO2 (conflicting signals)
		"temp": 37.5,                  # Elevated
		"ax": 0.4,
		"ay": 0.25,
		"az": 0.3,
	},
}


GSR_NOISE_SIGMA = 100.0        # ±100 from baseline
SPO2_NOISE_SIGMA = 0.5         # ±0.5% from baseline
TEMP_NOISE_SIGMA = 0.2         # ±0.2°C from baseline
ACCEL_AXIS_NOISE_SIGMA = 0.02 * (ACCEL_AXIS_MAX - ACCEL_AXIS_MIN)


def _clip(value: float, lower: float, upper: float) -> float:
	return float(np.clip(value, lower, upper))


def _normalize(value: float, lower: float, upper: float) -> float:
	value = _clip(value, lower, upper)
	return (value - lower) / (upper - lower)


def _validate_mode(mode: str) -> None:
	if mode not in MODE_CONFIG:
		raise ValueError(
			f"Unsupported mode '{mode}'. Expected one of: {list(MODE_CONFIG.keys())}"
		)


def get_simulated_sample(mode: str) -> Dict[str, float]:
	"""Return one physiologically plausible sensor sample for a mode."""
	_validate_mode(mode)
	base = MODE_CONFIG[mode]

	gsr = _clip(np.random.normal(base["gsr"], GSR_NOISE_SIGMA), GSR_MIN, GSR_MAX)
	spo2 = _clip(np.random.normal(base["spo2"], SPO2_NOISE_SIGMA), SPO2_MIN, SPO2_MAX)
	temp = _clip(np.random.normal(base["temp"], TEMP_NOISE_SIGMA), TEMP_MIN, TEMP_MAX)
	ax = _clip(
		np.random.normal(base["ax"], ACCEL_AXIS_NOISE_SIGMA),
		ACCEL_AXIS_MIN,
		ACCEL_AXIS_MAX,
	)
	ay = _clip(
		np.random.normal(base["ay"], ACCEL_AXIS_NOISE_SIGMA),
		ACCEL_AXIS_MIN,
		ACCEL_AXIS_MAX,
	)
	az = _clip(
		np.random.normal(base["az"], ACCEL_AXIS_NOISE_SIGMA),
		ACCEL_AXIS_MIN,
		ACCEL_AXIS_MAX,
	)

	return {
		"gsr": float(round(gsr, 3)),
		"spo2": float(round(spo2, 3)),
		"temp": float(round(temp, 3)),
		"ax": float(round(ax, 3)),
		"ay": float(round(ay, 3)),
		"az": float(round(az, 3)),
	}


def get_simulated_window(mode: str, n_samples: int = 500) -> np.ndarray:
	"""Return normalized window shaped (n_samples, 4).

	Output columns: [gsr_norm, spo2_norm, temp_norm, accel_magnitude_norm].
	Uses baseline-relative normalization matching esp32_reader.py.
	"""
	_validate_mode(mode)
	window = np.zeros((n_samples, 4), dtype=np.float32)

	# Normalization ranges (matching esp32_reader.py)
	gsr_range = 1125.0    # ±1125 from baseline 1625 (500-2750 range)
	spo2_range = 5.0      # ±5% from baseline 90.5
	temp_range = 1.0      # ±1°C from baseline 36.5 (spans 35.5-37.5)

	for i in range(n_samples):
		sample = get_simulated_sample(mode)
		accel_mag = float(
			np.sqrt(sample["ax"] ** 2 + sample["ay"] ** 2 + sample["az"] ** 2)
		)

		# Baseline-relative normalization (maps normal ~ 0.5, stress -> extremes)
		gsr_norm = _clip((sample["gsr"] - GSR_BASELINE) / gsr_range + 0.5, 0.0, 1.0)
		spo2_norm = _clip((sample["spo2"] - SPO2_BASELINE) / spo2_range + 0.5, 0.0, 1.0)
		temp_norm = _clip((sample["temp"] - TEMP_BASELINE) / temp_range + 0.5, 0.0, 1.0)
		accel_norm = _normalize(accel_mag, ACCEL_MAG_MIN, ACCEL_MAG_MAX)

		window[i, 0] = gsr_norm
		window[i, 1] = spo2_norm
		window[i, 2] = temp_norm
		window[i, 3] = accel_norm

	return window


def get_simulated_window_as_raw(mode: str) -> Dict[str, float]:
	"""
	Return one simulated raw sensor reading as a dict (not normalized).
	Format matches ESP32 output: GSR, SPO2, TEMP, AX, AY, AZ, BPM, ECG, etc.
	"""
	_validate_mode(mode)
	base = MODE_CONFIG[mode]

	gsr = _clip(
		np.random.normal(base["gsr"], GSR_NOISE_SIGMA),
		GSR_MIN,
		GSR_MAX,
	) * 4095.0 / GSR_MAX  # Scale to 12-bit ADC range

	spo2 = _clip(
		np.random.normal(base["spo2"], SPO2_NOISE_SIGMA),
		SPO2_MIN,
		SPO2_MAX,
	)

	temp = _clip(
		np.random.normal(base["temp"], TEMP_NOISE_SIGMA),
		TEMP_MIN,
		TEMP_MAX,
	)

	ax = _clip(
		np.random.normal(base["ax"], ACCEL_AXIS_NOISE_SIGMA),
		ACCEL_AXIS_MIN,
		ACCEL_AXIS_MAX,
	)
	ay = _clip(
		np.random.normal(base["ay"], ACCEL_AXIS_NOISE_SIGMA),
		ACCEL_AXIS_MIN,
		ACCEL_AXIS_MAX,
	)
	az = _clip(
		np.random.normal(base["az"], ACCEL_AXIS_NOISE_SIGMA),
		ACCEL_AXIS_MIN,
		ACCEL_AXIS_MAX,
	)

	bpm = 72 + np.random.normal(0, 5)  # ~72 BPM with variation
	ecg = 2048 + np.random.normal(0, 300)  # DAC center + noise

	return {
		"GSR": float(gsr),
		"SPO2": float(spo2),
		"TEMP": float(temp),
		"AX": float(ax),
		"AY": float(ay),
		"AZ": float(az),
		"BPM": float(bpm),
		"ECG": float(np.clip(ecg, 0, 4095)),
		"ECG_HR": float(bpm),
		"LO": 0,  # Electrodes connected
		"RISK": 0,
		"STATE": "SIM",
	}
