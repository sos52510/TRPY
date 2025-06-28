# motor.py
# ---------------------------------------------------------------------------
#  Arduino 端韌體對照 (motor.ino)：
#  · G<pulse>  → 絕對脈衝定位，完成後傳 "OK"
#  · S<idx>    → 同步當前 idx，不動作
#  · "READY"   → 開機握手
# ---------------------------------------------------------------------------

import sys
import subprocess
import time
from typing import Optional

# ----------------- 依賴自動檢查（pyserial） -----------------
def _ensure_serial():
    try:
        import serial  # noqa: F401
    except ImportError:
        print('[motor] pyserial 不存在，嘗試自動安裝…')
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--user", "pyserial"]
        )
        time.sleep(1)  # 讓 pip 完成安裝
    finally:
        global serial  # type: ignore
        import serial  # noqa: E402
_ensure_serial()
# -----------------------------------------------------------

from serial.tools import list_ports

try:
    from PyQt5.QtCore import QObject, pyqtSignal
except ImportError:
    # 允許在非 GUI context 使用
    class _Dummy(QObject):  # type: ignore
        pass
    QObject = _Dummy  # type: ignore
    def pyqtSignal(*_a, **_kw):  # type: ignore
        return lambda _f: _f


class MotorArduino(QObject):  # pylint: disable=too-many-instance-attributes
    """
    控制 Arduino 步進馬達；以「idx = pulse / 10」為邏輯單位。
    · SAFE_MIN_IDX–SAFE_MAX_IDX 之外拒絕動作並 emit hitLimit
    """

    hitLimit = pyqtSignal(int)   # 送出觸及極限的 idx
    positionChanged = pyqtSignal(int)   # 位置更新


    # ---------- 可依硬體需求微調 ----------
    BAUDRATE = 115200
    PULSES_PER_IDX = 10
    SAFE_MIN_IDX = 20
    SAFE_MAX_IDX = 990
    TIME_PER_PULSE = 0.05       # 秒；依實際測量修改
    TIME_BUFFER = 0.5            # 固定額外 buffer
    # -------------------------------------

    def __init__(self, port: Optional[str] = None, timeout: float = 2.0) -> None:
        super().__init__()
        self._ser: Optional[serial.Serial] = None
        self._pos_idx = 0
        self._timeout = timeout
        self._connect(port)

    # ------------------------------------------------------------------
    # ⬇⬇ 公開屬性 / 方法
    # ------------------------------------------------------------------
    @property
    def position(self) -> int:
        """目前 idx 位置（軟體視角）"""
        return self._pos_idx

    @position.setter
    def position(self, idx: int) -> None:
        self._pos_idx = int(idx)
        # 同步給韌體，但不動作
        self._write(f"S{idx}")
        self.positionChanged.emit(self._pos_idx)

    def goto(self, target_idx: int) -> bool:
        """阻塞定位。成功 True / 失敗 False"""
        if not self._ser:
            raise RuntimeError("Serial not open")

        if target_idx < self.SAFE_MIN_IDX or target_idx > self.SAFE_MAX_IDX:
            self.hitLimit.emit(int(target_idx))
            return False

        if target_idx == self._pos_idx:
            return True  # 不必動作

        target_pulse = target_idx * self.PULSES_PER_IDX
        delta_pulse = abs(target_pulse - self._pos_idx * self.PULSES_PER_IDX)
        self._write(f"G{target_pulse}")

        # 計算 timeout（避免小步也等太久）
        est = delta_pulse * self.TIME_PER_PULSE + self.TIME_BUFFER
        if not self._wait_ok(est):
            raise RuntimeError("Motor no ACK")

        self._pos_idx = target_idx
        self.positionChanged.emit(self._pos_idx)
        return True

    def close(self) -> None:
        """Close serial port."""
        if self._ser:
            try:
                self._ser.close()
            finally:
                self._ser = None
        
    # for 手動測試: python -m motor
    @classmethod
    def cli(cls) -> None:
        m = cls()
        print(">>> Motor ready. 輸入 idx（20–990）或 q 離開")
        while True:
            try:
                raw = input("idx> ").strip()
            except EOFError:
                break
            if raw.lower() in ("q", "quit", "exit"):
                break
            if raw.isdigit():
                idx = int(raw)
                try:
                    m.goto(idx)
                    print(f"  到達 idx {idx}")
                except Exception as exc:  # pylint: disable=broad-except
                    print("  Error:", exc)
        m.close()

    # ------------------------------------------------------------------
    # ⬇⬇ 私有函式
    # ------------------------------------------------------------------
    def _connect(self, port: Optional[str]) -> None:
        if port is None:
            # 自動找 VID/PID 或名稱包含 'Arduino'/'USB-SERIAL'
            port = self._auto_detect_port()
        if port is None:
            raise RuntimeError("找不到 Arduino COM 埠")
        self._ser = serial.Serial(port, self.BAUDRATE, timeout=0.1)
        # 清空開機訊息
        time.sleep(1.0)
        self._ser.reset_input_buffer()
        print(f"[motor] Connected on {port}")

    def _auto_detect_port(self) -> Optional[str]:
        for p in list_ports.comports():
            if ("Arduino" in p.description) or ("USB-SERIAL" in p.description):
                return p.device
        # fallback: 第一個 ttyUSB / COM
        ports = list_ports.comports()
        return ports[0].device if ports else None

    def _write(self, msg: str) -> None:
        if not self._ser:
            raise RuntimeError("Serial not open")
        self._ser.reset_input_buffer()
        self._ser.write(f"{msg}\n".encode())

    def _wait_ok(self, tmax: float) -> bool:
        if not self._ser:
            return False
        deadline = time.time() + tmax
        buf = b""
        while time.time() < deadline:
            if self._ser.in_waiting:
                buf += self._ser.read(self._ser.in_waiting)
                if b"OK" in buf:
                    return True
                if b"ERR" in buf:
                    return False
            time.sleep(0.01)
        return False

if __name__ == "__main__":
    MotorArduino.cli()
