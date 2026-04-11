"""ESP32 serial reader utilities."""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import numpy as np
import serial
from serial.tools import list_ports


logger = logging.getLogger(__name__)


# ESP32 ADC commonly reports 0-4095 (12-bit). Keep parser tolerant to both
# legacy 0-1023 and 12-bit firmware output.
GSR_MIN, GSR_MAX = 0.0, 4095.0
SPO2_MIN, SPO2_MAX = 90.0, 100.0
TEMP_MIN, TEMP_MAX = 35.0, 40.0
ACCEL_MAG_MIN, ACCEL_MAG_MAX = 0.0, 20.0


class SerialNotFoundError(Exception):
	"""Raised when an ESP32 device cannot be discovered."""


def _normalize(value: float, lower: float, upper: float) -> float:
	value = float(np.clip(value, lower, upper))
	return (value - lower) / (upper - lower)


def parse_line(line):
	try:
		line = line.strip()
		if not line or ":" not in line:
			return None
		# Skip boot messages
		if any(x in line for x in ["BOOT", "FAIL", "OK", "started", "Scanning", "Found", "Init"]):
			return None
		parts = line.split(",")
		if len(parts) < 6:
			return None
		data = {}
		for part in parts:
			if ":" in part:
				key, val = part.split(":", 1)
				key = key.strip()
				val = val.strip()
				if key == "STATE":
					data[key] = val
				else:
					try:
						data[key] = float(val)
					except Exception:
						pass
		# Must have these minimum keys
		required = ["GSR", "SPO2", "TEMP", "AX"]
		if all(k in data for k in required):
			return data
		return None
	except Exception:
		return None


def normalize_reading(data):
	# Normalize to 0-1 range
	gsr_norm = min(data.get("GSR", 0) / 4095.0, 1.0)

	spo2_raw = data.get("SPO2", 0)
	# If SPO2 is 0 (no finger) use 0.5 as neutral
	if spo2_raw < 1:
		spo2_norm = 0.5
	else:
		spo2_norm = max(0, min((spo2_raw - 90) / 10.0, 1.0))

	temp_raw = data.get("TEMP", 36.5)
	temp_norm = max(0, min((temp_raw - 35.0) / 5.0, 1.0))

	ax = data.get("AX", 0)
	ay = data.get("AY", 0)
	az = data.get("AZ", 0)
	accel_mag = (ax**2 + ay**2 + az**2) ** 0.5
	accel_norm = min(accel_mag / 2.0, 1.0)

	return np.array([
		gsr_norm, spo2_norm, temp_norm, accel_norm
	], dtype=np.float32)


class ESP32Reader:
	def __init__(
		self,
		baud_rate: int = 115200,
		read_timeout: float = 0.2,
		scan_timeout: float = 1.0,
		preferred_port: Optional[str] = None,
	) -> None:
		self.baud_rate = baud_rate
		self.read_timeout = read_timeout
		self.scan_timeout = scan_timeout
		self.preferred_port = preferred_port
		self._serial: Optional[serial.Serial] = None
		self.port: Optional[str] = None
		self.last_raw: Dict[str, float] = {}
		self.last_stats: Dict[str, object] = {
			"port": None,
			"requested_samples": 0,
			"collected_samples": 0,
			"valid_lines": 0,
			"invalid_lines": 0,
			"elapsed_seconds": 0.0,
			"ok": False,
			"reason": "not_started",
			"last_valid_line": "",
		}

	def _detect_and_open(self) -> serial.Serial:
		if self.preferred_port:
			try:
				conn = serial.Serial(
					self.preferred_port,
					self.baud_rate,
					timeout=self.read_timeout,
				)
				conn.reset_input_buffer()
				self.port = self.preferred_port
				self._serial = conn
				return conn
			except Exception:
				# Fall back to scan if preferred port is temporarily unavailable.
				pass

		deadline = time.time() + self.scan_timeout
		last_exception: Optional[Exception] = None

		while time.time() < deadline:
			for port in list_ports.comports():
				try:
					conn = serial.Serial(
						port.device,
						self.baud_rate,
						timeout=self.read_timeout,
					)
					conn.reset_input_buffer()
					self.port = port.device
					self._serial = conn
					return conn
				except Exception as exc:  # pragma: no cover - hardware dependent
					last_exception = exc
					continue
			time.sleep(0.2)

		if last_exception:
			raise SerialNotFoundError("No ESP32 detected") from last_exception
		raise SerialNotFoundError("No ESP32 detected")

	def connect(self) -> serial.Serial:
		if self._serial and self._serial.is_open:
			return self._serial
		return self._detect_and_open()

	def close(self) -> None:
		if self._serial and self._serial.is_open:
			self._serial.close()
		self._serial = None

	def read_window(self, n_samples: int = 60, max_window_seconds: float = 2.5) -> Optional[np.ndarray]:
		"""Read serial stream and return normalized shape (n_samples, 4)."""
		try:
			conn = self.connect()
		except SerialNotFoundError:
			self.last_stats = {
				"port": self.preferred_port,
				"requested_samples": int(n_samples),
				"collected_samples": 0,
				"valid_lines": 0,
				"invalid_lines": 0,
				"elapsed_seconds": 0.0,
				"ok": False,
				"reason": "serial_not_found",
				"last_valid_line": "",
			}
			return None

		readings = []
		valid_lines = 0
		invalid_lines = 0
		attempts = 0
		last_valid_line = ""
		start_time = time.time()

		# Read lines from serial one by one
		while len(readings) < n_samples and attempts < 120:
			attempts += 1
			raw_line = conn.readline()
			if not raw_line:
				invalid_lines += 1
				continue
			line = raw_line.decode("utf-8", errors="ignore")
			# For each line call parse_line()
			data = parse_line(line)
			if data is None:
				invalid_lines += 1
				continue

			# If valid, call normalize_reading()
			reading = normalize_reading(data)
			readings.append(reading)
			valid_lines += 1
			last_valid_line = line.strip()
			self.last_raw = data

			# Add logging every 10 samples
			if len(readings) % 10 == 0:
				logger.info(f"[HW] collected {len(readings)}/{n_samples} valid samples")
				logger.info(
					f"[SERIAL] GSR={data['GSR']:.0f} | "
					f"SPO2={data['SPO2']:.1f} | "
					f"TEMP={data['TEMP']:.1f}°C | "
					f"BPM={data.get('BPM', 0):.0f} | "
					f"STATE={data.get('STATE','?')}"
				)

		# If after attempts we have fewer than n_samples readings, pad with last valid
		if len(readings) == 0:
			fallback = np.array([0.5, 0.5, 0.5, 0.0], dtype=np.float32)
			readings = [fallback for _ in range(n_samples)]
			reason = "no_valid_samples"
			ok = False
		elif len(readings) < n_samples:
			last_valid = readings[-1]
			while len(readings) < n_samples:
				readings.append(last_valid)
			reason = "padded_with_last_valid"
			ok = True
		else:
			reason = "ok"
			ok = True

		window = np.stack(readings, axis=0).astype(np.float32)
		self.last_stats = {
			"port": self.port,
			"requested_samples": int(n_samples),
			"collected_samples": int(len(readings)),
			"valid_lines": int(valid_lines),
			"invalid_lines": int(invalid_lines),
			"elapsed_seconds": round(float(time.time() - start_time), 3),
			"ok": bool(ok),
			"reason": reason,
			"last_valid_line": last_valid_line,
		}
		return window


def has_device(preferred_port: Optional[str] = None) -> bool:
	"""Check whether an ESP32-like serial device is discoverable."""
	reader = ESP32Reader(preferred_port=preferred_port)
	try:
		reader.connect()
		return True
	except SerialNotFoundError:
		return False
	finally:
		reader.close()
