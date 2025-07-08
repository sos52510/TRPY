import sys
from PyQt5 import QtCore, QtWidgets
from PyQt5 import QtGui
from drivers.motor import MotorArduino
from drivers.lockin import LockInNF5610B, LockInDummy
from models.mapper import Mapper
from widgets.calibration_widget import CalibrationWidget
from widgets.experiment_widget import ExperimentWidget
from widgets.live_plot_widget import LivePlotWidget
from widgets.lockin_param_widget import LockInParamWidget

##################################################
# 1. Lock-in 抽象層
def show_fatal(title: str, msg: str):
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical, title, msg)
    box.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint)      # 永遠置頂
    box.setWindowModality(QtCore.Qt.ApplicationModal)      # 阻塞主執行緒
    box.exec_()
    sys.exit(1)

def show_fatal_lockin(title: str, msg: str):
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical, title, msg)
    box.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint)      # 永遠置頂
    box.setWindowModality(QtCore.Qt.ApplicationModal)      # 阻塞主執行緒
    box.exec_()
    
class MultiTabMainWindow(QtWidgets.QMainWindow):
    def __init__(self, offline=False):
        super().__init__()
        self.setWindowTitle("熱調製光譜 GUI")
        self.statusBar().showMessage("Initializing…")
        
        self.mapper = Mapper()
        try:
            self.motor = MotorArduino()
        except Exception as e:  # noqa: broad-except
            show_fatal("Motor Error", str(e))

        if offline:
            self.lockin = LockInDummy()
            self.offline = True
        else:
            try:
                self.lockin = LockInNF5610B()
                self.offline = False
            except Exception as e:  # noqa: broad-except
                show_fatal_lockin("Lock‑in Error", f"無法連接 NF 5610B\n{e}")
                self.lockin = LockInDummy()
                self.offline = True
            
        tabs = QtWidgets.QTabWidget()
        self.mapper = Mapper()
        live_tab = LivePlotWidget()
        ctrl_tab = ExperimentWidget(self.lockin, live_tab, tabs, self.motor, self.mapper)
        cal_tab = CalibrationWidget(self.motor, self.mapper)
        cal_tab.cal_loaded.connect(ctrl_tab.set_calibration)
        tabs.addTab(ctrl_tab, "掃描控制")
        tabs.addTab(live_tab, "即時圖")   
        tabs.addTab(cal_tab, "馬達校正")
        tabs.addTab(QtWidgets.QLabel("溫控頁 (待完成)"), "溫度控制")
        tabs.addTab(LockInParamWidget(self.lockin), "Lock‑in 參數")
        self.setCentralWidget(tabs)
        
        live_tab.btn_stop.clicked.connect(ctrl_tab.stop_scan)
        # 建立“空白鍵”應用層快捷鍵
        self.shortcut_stop = QtWidgets.QShortcut(QtGui.QKeySequence("Space"), self)
        self.shortcut_stop.setContext(QtCore.Qt.ApplicationShortcut)   # 全域作用
        self.shortcut_stop.activated.connect(ctrl_tab.stop_scan)       # 直接叫控制頁函式
        self.shortcut_stop.setEnabled(False)      # 預設關閉

        # 掃描開始/結束時開關
        ctrl_tab.scan_started.connect(lambda: self.shortcut_stop.setEnabled(True))
        ctrl_tab.scan_finished.connect(lambda: self.shortcut_stop.setEnabled(False))

        st = "Online(" + self.lockin.name() + ")" if not self.offline else "Offline(Dummy)"
        self.statusBar().showMessage(f"Lock‑in: {st}")
    
    # MultiTabMainWindow
    def stop_all_threads(self):
        """Gracefully stop any running worker threads."""
        for name in ("scan_thread", "jog_thread", "check_thread"):
            th = getattr(self, name, None)
            if th and th.isRunning():
                th.requestInterruption()
                th.quit()
                th.wait()

    def closeEvent(self, event):  # noqa: D401
        """Cleanup resources on window close."""
        try:
            self.stop_all_threads()
        finally:
            if hasattr(self, "motor"):
                try:
                    self.motor.close()
                except Exception:
                    pass
            event.accept()
