"""Background serial reader thread — opens port ONCE and continuously reads."""

import logging
import threading
import time
from collections import deque
from typing import Optional

import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)


class SerialReaderThread:
    """
    Singleton background thread that maintains an open serial connection
    and continuously reads incoming data into a thread-safe buffer.
    
    Key properties:
    - Port opened ONCE at start, never closed until stop()
    - Continuous read loop independent of Streamlit reruns
    - Thread-safe buffer (deque with maxlen) for latest readings
    - Non-blocking get_latest() and get_buffer_snapshot() methods
    """

    def __init__(self, port: str = "COM3", baud: int = 115200):
        self.port = port
        self.baud = baud
        self._buffer = deque(maxlen=200)
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._connected = False
        self._last_raw = None

    def start(self):
        """Start the background read thread if not already running."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="SerialReaderThread",
        )
        self._thread.start()
        logger.info(f"[SERIAL THREAD] Started on {self.port}")

    def stop(self):
        """Stop the background read thread."""
        self._running = False

    @property
    def connected(self) -> bool:
        """Returns True if port is currently open and readable."""
        return self._connected

    def get_latest(self) -> Optional[dict]:
        """
        Atomically retrieve the most recent parsed sample.
        Returns None if no sample has been read yet.
        """
        with self._lock:
            if self._last_raw:
                return dict(self._last_raw)
            return None

    def get_buffer_snapshot(self, n: int = 30) -> list:
        """
        Atomically retrieve the last n samples from the buffer.
        If fewer than n samples available, returns all available samples.
        """
        with self._lock:
            items = list(self._buffer)
        return items[-n:] if len(items) >= n else items

    def _read_loop(self):
        """
        Main loop: open port, continuously read lines, parse, store in buffer.
        Handles reconnection on port errors.
        """
        ser = None
        while self._running:
            try:
                # Open or reconnect to port if needed
                if ser is None or not ser.is_open:
                    ser = serial.Serial(
                        self.port,
                        self.baud,
                        timeout=2,
                    )
                    self._connected = True
                    logger.info(
                        f"[SERIAL THREAD] Port {self.port} opened successfully"
                    )

                # Read one line from serial
                line = ser.readline().decode("utf-8", errors="ignore").strip()

                if not line or ":" not in line:
                    continue

                # Skip boot/debug messages
                skip = [
                    "BOOT",
                    "FAIL",
                    "OK",
                    "started",
                    "Scanning",
                    "Found",
                    "Init",
                    "MAX",
                    "MPU",
                    "DHT",
                    "AD8232",
                ]
                if any(x in line for x in skip):
                    continue

                # Parse the line into a dict
                parsed = self._parse(line)
                if parsed:
                    with self._lock:
                        self._buffer.append(parsed)
                        self._last_raw = parsed

            except serial.SerialException as e:
                self._connected = False
                logger.warning(f"[SERIAL THREAD] Port error: {e}")
                if ser:
                    try:
                        ser.close()
                    except:
                        pass
                    ser = None
                time.sleep(2)

            except Exception as e:
                logger.warning(f"[SERIAL THREAD] Unexpected error: {e}")
                time.sleep(0.5)

    def _parse(self, line: str) -> Optional[dict]:
        """
        Parse a CSV line from ESP32:
        GSR:1234,SPO2:98.5,TEMP:36.2,AX:0.1,AY:-0.05,AZ:0.95,BPM:72,ECG:2048,ECG_HR:71,LO:0,RISK:0,STATE:NORMAL
        
        Returns dict with parsed fields, or None if parse fails or required fields missing.
        """
        try:
            parts = line.split(",")
            if len(parts) < 6:
                return None

            data = {}
            for part in parts:
                if ":" in part:
                    k, v = part.split(":", 1)
                    k = k.strip().upper()
                    v = v.strip()

                    if k == "STATE":
                        data[k] = v
                    else:
                        try:
                            data[k] = float(v)
                        except (ValueError, TypeError):
                            pass

            # Require minimum fields for a valid reading
            required = ["GSR", "SPO2", "TEMP", "AX"]
            if all(k in data for k in required):
                return data
            return None

        except Exception:
            return None


# Global singleton instance and lock
_reader_instance = None
_reader_lock = threading.Lock()


def get_serial_reader(
    port: str = "COM3",
    baud: int = 115200,
) -> SerialReaderThread:
    """
    Get or create the global SerialReaderThread singleton.
    Starts the background thread on first call.
    
    Safe to call from multiple threads (uses lock).
    """
    global _reader_instance

    with _reader_lock:
        if _reader_instance is None:
            _reader_instance = SerialReaderThread(port, baud)
            _reader_instance.start()
    return _reader_instance
