from PyQt5 import QtCore, QtWidgets
from workers import MotorMoveWorker

class CalibrationWidget(QtWidgets.QWidget):
    """手動建立 / 載入校正表；支援 jog 微移馬達。"""
    cal_loaded = QtCore.pyqtSignal(list)          # [(nm, phys_idx), …]
    
    def __init__(self, motor, mapper, parent=None):
        super().__init__(parent)
        self.motor = motor
        self.mapper = mapper
        self.cal_tbl = []                         # 暫存校正點
        self._idx_known = False

        # ───── 控件 ─────
        self.spn_nm   = QtWidgets.QDoubleSpinBox(); self.spn_nm.setRange(100,3000); self.spn_nm.setDecimals(1); self.spn_nm.setSingleStep(0.1)
        self.spn_idx_now  = QtWidgets.QSpinBox()
        self.spn_idx_now.setRange(99, 999)              # -1 當作「尚未設定」
        self.spn_idx_now.setSpecialValueText("— 未設定 —")
        self.spn_idx_now.setValue(99)                   # 預設顯示「— 未設定 —」
        self.spn_step = QtWidgets.QDoubleSpinBox(); self.spn_step.setRange(0.1,200); self.spn_step.setDecimals(1); self.spn_step.setValue(1.0)
        self.btn_ccw  = QtWidgets.QPushButton("↺")
        self.btn_cw   = QtWidgets.QPushButton("↻")
        self.btn_add  = QtWidgets.QPushButton("加入校正點")
        self.tbl_calib  = QtWidgets.QListWidget()
        self.btn_save = QtWidgets.QPushButton("存成 CSV")
        self.btn_load = QtWidgets.QPushButton("載入校正檔…")

        self.tbl_calib = QtWidgets.QTableWidget(); self.tbl_calib.setColumnCount(2)
        self.tbl_calib.setHorizontalHeaderLabels(["idx", "nm"])
        self.lbl_status = QtWidgets.QLabel("— 未載入 —")

        # ───── 版面 ─────
        g = QtWidgets.QGridLayout(self)
        g.setContentsMargins(4,4,4,4);  g.setVerticalSpacing(2)
        g.addWidget(QtWidgets.QLabel("光譜儀波長 (nm)"), 0,0); g.addWidget(self.spn_nm, 0,1)
        g.addWidget(QtWidgets.QLabel("計數器位置"),       0,2); g.addWidget(self.spn_idx_now,0,3)
        g.addWidget(QtWidgets.QLabel("步距 (nm)"),      1,0); g.addWidget(self.spn_step,1,1)
        g.addWidget(self.btn_ccw, 1,2); g.addWidget(self.btn_cw, 1,3)
        g.addWidget(self.btn_add, 0,4)
        g.addWidget(self.tbl_calib, 2,0,1,5)
        g.addWidget(self.btn_save,3,3); g.addWidget(self.btn_load,3,4)
    
        g.addWidget(self.lbl_status, 3, 0, 1, 2)

        # ───── 事件 ─────
        self.btn_ccw.clicked.connect(lambda: self.jog(-1))
        self.btn_cw .clicked.connect(lambda: self.jog(+1))
        self.btn_add.clicked.connect(self.add_point)
        self.btn_save.clicked.connect(self.on_save_calib)
        self.btn_load.clicked.connect(self.load_calibration)
        self.motor.positionChanged.connect(self._on_motor_pos)
        self.motor.hitLimit.connect(self._on_limit)
        self.spn_idx_now.editingFinished.connect(self._on_idx_edit)

    def _on_motor_pos(self, val: int) -> None:
        self._idx_known = True
        self.spn_idx_now.setValue(val)

    def _on_idx_edit(self) -> None:
        self._idx_known = True
        self.motor.position = self.spn_idx_now.value()

    def _on_limit(self, idx: int) -> None:
        QtWidgets.QMessageBox.warning(self, "觸及極限", f"位置 {idx} 超出安全範圍")


    # ───── 功能 ─────
    def _nm_to_pulse(self, nm_val: float) -> int:
        if len(self.cal_tbl) >= 2:
            xs, ys = zip(*self.cal_tbl)
            if xs[-1] == xs[0]:          # 防除以 0
                return int(round(nm_val))
            slope = (ys[-1]-ys[0])/(xs[-1]-xs[0])
            return int(round(nm_val * slope))
        return int(round(nm_val))

    
    def jog(self, sign: int):
        if hasattr(self, "worker") and self.worker.isRunning():
            return

        if not self._idx_known:
            QtWidgets.QMessageBox.warning(self, "未知計數器", "請先輸入目前計數器位置！")
            return

        step_nm = self.spn_step.value()
        if self.mapper.point_count() >= 2:
            # 已有正式校正 → 用 Mapper 內插求「這一步」等幾格 idx
            nm_now = self.spn_nm.value()
            idx_now = self.mapper.idx_from_nm(nm_now)
            idx_next = self.mapper.idx_from_nm(nm_now + step_nm)
            pulse_step = int(round(abs(idx_next - idx_now)))
        else:
            # 還沒正式校正 → 用簡單斜率估計
            pulse_step = self._nm_to_pulse(step_nm)

        target_idx = max(0, min(999, self.motor.position + sign * pulse_step))
        self.worker = MotorMoveWorker(self.motor, target_idx, self)
        self.worker.finished.connect(self._on_motor_pos)
        self.worker.start()

    def add_point(self):
        lam_nm = self.spn_nm.value()
        pulse  = self.spn_idx_now.value()

        if not self._idx_known:
            QtWidgets.QMessageBox.warning(self, "未知計數器", "請先輸入目前計數器位置！")
            return

        # ① 寫入 Mapper
        self.mapper.add_point(idx=pulse, nm=lam_nm)

        # ② 本地暫存
        self.cal_tbl.append((lam_nm, pulse))

        # ③ 更新 GUI（QTableWidget 版本）
        row = self.tbl_calib.rowCount()
        self.tbl_calib.insertRow(row)

        self.tbl_calib.setItem(row, 0, QtWidgets.QTableWidgetItem(str(pulse)))
        self.tbl_calib.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{lam_nm:.1f}"))

        # ④ 發 signal 讓 ExperimentWidget 重建校正表
        self.cal_loaded.emit(list(zip(self.mapper.nm_arr, self.mapper.idx_arr)))
    
    def on_save_calib(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "存校正檔", "", "CSV (*.csv);;All Files (*)"
        )
        if filename:
            try:
                self.mapper.save(filename)
                QtWidgets.QMessageBox.information(self, "完成", f"已寫入 {filename}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "存檔失敗", str(e))

    def load_calibration(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "載入校正 CSV", "", "CSV (*.csv)")

        if not path:          # 使用者按取消
            return

        try:
            # 1) 交給 Mapper 讀檔（假設回傳 idx 與 nm 陣列）
            self.mapper.load(path)
            idx_arr = self.mapper.idx_arr       # 直接取陣列
            nm_arr  = self.mapper.nm_arr       
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "載入失敗", str(e))
            return

        # 2) **把資料灌進表格**
        self.tbl_calib.setRowCount(len(idx_arr))
        for row, (idx, nm) in enumerate(zip(idx_arr, nm_arr)):
            self.tbl_calib.setItem(row, 0, QtWidgets.QTableWidgetItem(str(idx)))
            self.tbl_calib.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{nm:.2f}"))

        # 3) **把狀態 flag 打開，供 ExperimentWidget 檢查**
        self.mapper.loaded = True              # ← 你原本的屬性名可能叫 ready/valid
        self.lbl_status.setText("✔ 已成功載入")  # （可選）把提示文字換成打勾

        self.cal_loaded.emit(list(zip(self.mapper.nm_arr, self.mapper.idx_arr)))
