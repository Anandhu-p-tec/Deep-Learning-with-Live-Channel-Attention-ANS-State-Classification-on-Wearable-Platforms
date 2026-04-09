"""ESP32 serial reader utilities."""

from __future__ import annotations

import time
from typing import Dict, Optional

import numpy as np
import serial
from serial.tools import list_ports


GSR_MIN, GSR_MAX = 0.0, 1023.0
SPO2_MIN, SPO2_MAX = 90.0, 100.0
TEMP_MIN, TEMP_MAX = 35.0, 40.0
ACCEL_MAG_MIN, ACCEL_MAG_MAX = 0.0, 20.0


class SerialNotFoundError(Exception):
	"""Raised when an ESP32 device cannot be discovered."""


def _normalize(value: float, lower: float, upper: float) -> float:
	value = float(np.clip(value, lower, upper))
	return (value - lower) / (upper - lower)


def parse_line(line: str) -> Dict[str, float]:
	"""Parse a serial line into sensor values.

	Expected input format:
	GSR:512,SPO2:98.2,TEMP:36.5,AX:0.1,AY:0.02,AZ:9.8
	"""
	expected_keys = ["GSR", "SPO2", "TEMP", "AX", "AY", "AZ"]
	parts = line.strip().split(",")
	if len(parts) != 6:
		raise ValueError(f"Invalid serial line format: {line!r}")

	parsed = {}
	for part in parts:
		if ":" not in part:
			raise ValueError(f"Invalid field format: {part!r}")
		key, value = part.split(":", 1)
		key = key.strip().upper()
		parsed[key] = float(value.strip())

	missing = [k for k in expected_keys if k not in parsed]
	if missing:
		raise ValueError(f"Missing fields in serial line: {missing}")

	return {
		"gsr": parsed["GSR"],
		"spo2": parsed["SPO2"],
		"temp": parsed["TEMP"],
		"ax": parsed["AX"],
		"ay": parsed["AY"],
		"az": parsed["AZ"],
	}


class ESP32Reader:
	def __init__(
		self,
		baud_rate: int = 115200,
		read_timeout: float = 1.0,
		scan_timeout: float = 3.0,
	) -> None:
		self.baud_rate = baud_rate
		self.read_timeout = read_timeout
		self.scan_timeout = scan_timeout
		self._serial: Optional[serial.Serial] = None
		self.port: Optional[str] = None

	def _detect_and_open(self) -> serial.Serial:
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

	def read_window(self, n_samples: int = 500) -> Optional[np.ndarray]:
		"""Read and normalize n_samples into shape (n_samples, 4).

		Returns None if serial read/parsing fails mid-window.
		"""
		try:
			conn = self.connect()
		except SerialNotFoundError:
			return None

		window = np.zeros((n_samples, 4), dtype=np.float32)

		for i in range(n_samples):
			try:
				raw_line = conn.readline()
				if not raw_line:
					return None
				decoded = raw_line.decode("utf-8", errors="ignore")
				sample = parse_line(decoded)
			except Exception:  # pragma: no cover - hardware dependent
				return None

			accel_mag = float(
				np.sqrt(sample["ax"] ** 2 + sample["ay"] ** 2 + sample["az"] ** 2)
			)
			window[i, 0] = _normalize(sample["gsr"], GSR_MIN, GSR_MAX)
			window[i, 1] = _normalize(sample["spo2"], SPO2_MIN, SPO2_MAX)
			window[i, 2] = _normalize(sample["temp"], TEMP_MIN, TEMP_MAX)
			window[i, 3] = _normalize(accel_mag, ACCEL_MAG_MIN, ACCEL_MAG_MAX)

		return window


def has_device() -> bool:
	"""Check whether an ESP32-like serial device is discoverable."""
	reader = ESP32Reader()
	try:
		reader.connect()
		return True
	except SerialNotFoundError:
		return False
	finally:
		reader.close()
