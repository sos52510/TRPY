# drivers/motor.py
# ---------------------------------------------------------------------------
#  Arduino 韌體協定：
#    · G<pulse>  → 絕對脈衝定位，完成後回傳 "OK"
#    · S<idx>    → 同步軟體 idx，不動作
# ---------------------------------------------------------------------------

import sys, subprocess, time, threading
from typing import Optional

# ---------- 自動確保 pyserial ----------
def _ensure_serial():
    try:
        import serial  # noqa: F401
    except ImportError:
        print('[motor] pyserial 缺失，嘗試安裝…')
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "pyserial"])
        time.sleep(1)
    finally:
        global serial  # type: ignore
        import serial  # noqa: E402
_ensure_serial()
from serial.tools import list_ports
# --------------------------------------

try:
    from PyQt5.QtCore import QObject, pyqtSignal
except ImportError:
    class QObject: pass                        # type: ignore
    def pyqtSignal(*_a, **_k): return lambda f: f  # type: ignore

class MotorArduino(QObject):
    hitLimit        = pyqtSignal(int)
    positionChanged = pyqtSignal(int)

    BAUDRATE       = 115200
    TIMEOUT_BUFFER = 0.5         # s，加在估算時間後
    PULSE_PER_IDX  = 10          # 1 idx = 10 pulse
    PULSE_TIME     = 0.002       # s，每脈衝驅動時間

    _lock = threading.Lock()

    def __init__(self, port: Optional[str] = None) -> None:
        super().__init__()
        self._ser = serial.Serial(self._detect_port(port), self.BAUDRATE, timeout=0.1)
        time.sleep(1)
        self._ser.reset_input_buffer()
        self._pos_idx = 0
        print(f"[motor] Connected on {self._ser.port}")

    # ---------------- 公開屬性 ----------------
    @property
    def position(self) -> int:
        return self._pos_idx

    @position.setter
    def position(self, idx: int) -> None:
        self._pos_idx = int(idx)
        self._write(f"S{idx}")
        self.positionChanged.emit(self._pos_idx)

    # ---------------- 主要動作 ----------------
    def goto(self, idx: int) -> None:
        with self._lock:
            if idx == self._pos_idx:
                return
            pulse = idx * self.PULSE_PER_IDX
            delta = abs(pulse - self._pos_idx * self.PULSE_PER_IDX)
            est   = delta * self.PULSE_TIME + self.TIMEOUT_BUFFER

            self._write(f"G{pulse}")
            self._wait_ok(est)

            self._pos_idx = idx
            self.positionChanged.emit(idx)

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ---------------- 私有工具 ----------------
    def _detect_port(self, p_hint: Optional[str]) -> str:
        if p_hint:
            return p_hint
        for p in list_ports.comports():
            if ("Arduino" in p.description) or ("USB-SERIAL" in p.description):
                return p.device
        if not list_ports.comports():
            raise RuntimeError("找不到任何 COM Port")
        return list_ports.comports()[0].device

    def _write(self, msg: str) -> None:
        self._ser.reset_input_buffer()
        self._ser.write(f"{msg}\n".encode())

    def _wait_ok(self, tmax: float) -> None:
        deadline = time.time() + tmax
        buf = b""
        while time.time() < deadline:
            if self._ser.in_waiting:
                buf += self._ser.readline()
                if b"OK" in buf:
                    return
                if b"ERR" in buf:
                    raise RuntimeError("Motor report ERR")
            time.sleep(0.01)
        raise RuntimeError("Motor no ACK")

    # ---------------- CLI 測試 ----------------
    @classmethod
    def cli(cls) -> None:
        m = cls()
        try:
            while True:
                raw = input("idx (q=quit)> ").strip()
                if raw.lower() in ("q", "quit"):
                    break
                if raw.isdigit():
                    m.goto(int(raw))
                    print("  ok")
        finally:
            m.close()

if __name__ == "__main__":
    MotorArduino.cli()
