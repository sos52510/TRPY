import numpy as np
import time
from PyQt5 import QtCore

class ScanWorker(QtCore.QThread):
    """Background scan: move motor → 讀 lock-in → emit data"""

    point_ready = QtCore.pyqtSignal(float, float, float, float)   # ev, x/edc, y/edc, edc
    run_complete = QtCore.pyqtSignal(object, object, object)      # ev_arr, x_arr, y_arr

    def __init__(self, lockin, motor, idx_arr, ev_arr, repeat: int, ui_widget):
        super().__init__()
        self.lockin = lockin
        self.motor = motor
        self.idx_arr = idx_arr
        self.ev_arr = ev_arr
        self.repeat = repeat
        self.ui = ui_widget

    def run(self) -> None:
        for _ in range(self.repeat):
            if self.isInterruptionRequested():
                return
            xs, ys = [], []
            for idx, ev in zip(self.idx_arr, self.ev_arr):
                self.motor.goto(idx)
                if self.isInterruptionRequested():
                    return
                time.sleep(0.05)                     # lock-in settle
                x, y, edc = self.lockin.read_xyz()
                if edc == 0:
                    QtCore.QMetaObject.invokeMethod(
                        self.ui,
                        "show_error_dialog",
                        QtCore.Qt.QueuedConnection,
                        QtCore.Q_ARG(str, f"{ev:.3f} eV: EDC = 0; aborted"),
                    )
                    return
                xs.append(x / edc)
                ys.append(y / edc)
                self.point_ready.emit(ev, xs[-1], ys[-1], edc)
            self.run_complete.emit(self.ev_arr.copy(), np.asarray(xs), np.asarray(ys))
            
##################################################
# 7.AutoCheckWorker
##################################################
class AutoCheckWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str)  # "" = OK; 其他 = 錯誤訊息

    def __init__(self, motor, idx0: int, idx1: int):
        super().__init__()
        self.motor = motor
        self.idx0 = idx0
        self.idx1 = idx1

    def run(self) -> None:
        step = 1 if self.idx1 >= self.idx0 else -1
        total = abs(self.idx1 - self.idx0) + 1
        for i, idx in enumerate(range(self.idx0, self.idx1 + step, step), 1):
            if self.isInterruptionRequested():
                self.finished.emit("中斷")
                return
            try:
                self.motor.goto(idx)
            except Exception as e:
                self.finished.emit(str(e))
                return
            self.progress.emit(int(i / total * 100))
            time.sleep(0.02)
        self.finished.emit("")
        
class MotorMoveWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(int)      # 把真正位置回傳給 GUI
    def __init__(self, motor, idx, parent=None):
        super().__init__(parent)
        self.motor = motor
        self.idx = idx

    def run(self):
        self.motor.goto(self.idx)
        self.finished.emit(self.idx)

