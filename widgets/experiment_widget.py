import numpy as np
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtWidgets import QFileDialog
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import os
from collections import deque
from workers import ScanWorker, AutoCheckWorker
##################################################
# 1. Lock-in 抽象層

class ExperimentWidget(QtWidgets.QWidget):
    """控制頁：負責參數設定、掃描啟停、平均/自動存檔、載入舊平均。
    即時繪圖完全委派給 LivePlotWidget（由 MainWindow 傳入）。"""

    scan_started  = QtCore.pyqtSignal()
    scan_finished = QtCore.pyqtSignal()

    def __init__(self, lockin, live_widget, parent, motor, mapper):
        super().__init__(parent)
        self.lockin = lockin
        self.motor = motor
        self.mapper = mapper
        self.live_widget = live_widget  # LivePlotWidget 實例
        self.tab_widget = parent
        self.cal_table = None      # ★ 新增：存 [(idx_user, idx_phys), ...]

        # ---------------- 掃描/平均狀態 ----------------
        self.completed_runs = []   # [(ev, x, y), ...]
        self.current_ev, self.current_x, self.current_y = [], [], []
        self.pending_runs   = []   # 累積 N 次就平均存檔
        self.saved_files    = deque()
        self.save_dir       = "./backup"; os.makedirs(self.save_dir, exist_ok=True)
        self.batch_counter  = 0     # 已寫出平均檔批數
      
        # ---------------- 控件 ----------------
        self._build_controls()

    # -------------------------------------------------
    # 控件建構
    # -------------------------------------------------
    def _build_controls(self):
        # 參數 SpinBox
        self.spn_ev_start = QtWidgets.QDoubleSpinBox(); self.spn_ev_start.setRange(0.1,10.0); self.spn_ev_start.setDecimals(3); self.spn_ev_start.setValue(1.93); self.spn_ev_start.setSingleStep(0.001)
        self.spn_ev_end   = QtWidgets.QDoubleSpinBox(); self.spn_ev_end.setRange(0.1,10.0); self.spn_ev_end.setDecimals(3); self.spn_ev_end.setValue(2.0);  self.spn_ev_end.setSingleStep(0.001)
        self.spn_ev_step  = QtWidgets.QDoubleSpinBox(); self.spn_ev_step.setRange(0.001,1.0); self.spn_ev_step.setDecimals(3); self.spn_ev_step.setValue(0.001); self.spn_ev_step.setSingleStep(0.001)
        self.spn_repeat   = QtWidgets.QSpinBox();       self.spn_repeat.setRange(1,9999); self.spn_repeat.setValue(12)
        self.spn_wl_start = QtWidgets.QDoubleSpinBox(); self.spn_wl_start.setRange(100.0,3000.0); self.spn_wl_start.setValue(642.4); self.spn_wl_start.setSingleStep(0.1); self.spn_wl_start.setDecimals(1)
        self.spn_wl_end   = QtWidgets.QDoubleSpinBox(); self.spn_wl_end.setRange(100.0,3000.0); self.spn_wl_end.setValue(619.9); self.spn_wl_end.setSingleStep(0.1); self.spn_wl_end.setDecimals(1)
        self.spn_save_every = QtWidgets.QSpinBox(); self.spn_save_every.setRange(1,999); self.spn_save_every.setValue(3)
        self.spn_keep_files = QtWidgets.QSpinBox(); self.spn_keep_files.setRange(1,999); self.spn_keep_files.setValue(3)
        self.spn_wl_set = QtWidgets.QDoubleSpinBox(); self.spn_wl_set.setRange(100,3000); self.spn_wl_set.setDecimals(1); self.spn_wl_set.setValue(619.9); self.spn_wl_set.setSingleStep(0.1)
        self.spn_ev_set = QtWidgets.QDoubleSpinBox(); self.spn_ev_set.setRange(0.1,10.0); self.spn_ev_set.setDecimals(3); self.spn_ev_set.setValue(2.0); self.spn_ev_set.setSingleStep(0.001)
        self.spn_idx_now = QtWidgets.QSpinBox()
        self.spn_idx_now.setRange(0, 999)          # 視實際行程
        self.spn_idx_now.setValue(500)
        self.mapper.l0 = self.spn_wl_start.value()
        self.mapper.dl = abs(self.spn_wl_start.value() - self.spn_wl_end.value()) / (self.spn_ev_end.value()-self.spn_ev_start.value()) * self.spn_ev_step.value() * 1239.84193 / (self.spn_ev_start.value()**2)   # 若覺得複雜可手動填
        
        # 按鈕
        self.btn_start = QtWidgets.QPushButton("開始掃描")
        self.btn_resume = QtWidgets.QPushButton("繼續掃描")
        self.btn_resume.setEnabled(False)
        self.btn_save  = QtWidgets.QPushButton("手動儲存平均…")
        self.btn_load  = QtWidgets.QPushButton("載入平均檔…")
        self.btn_sel_dir = QtWidgets.QPushButton("選擇資料夾…")
        self.lbl_dir = QtWidgets.QLabel(self.save_dir)
        self.btn_autocheck = QtWidgets.QPushButton("Auto Check")
        self.btn_goto = QtWidgets.QPushButton("Go")

        self._ctrl_widgets = [self.spn_ev_start, self.spn_ev_end, self.spn_ev_step, self.spn_repeat,self.spn_wl_start, self.spn_wl_end, self.spn_save_every, self.spn_keep_files,self.btn_save, self.btn_load, self.btn_sel_dir]

        # ---- 版面：參數格 ----
        param_w = QtWidgets.QWidget(); grid = QtWidgets.QGridLayout(param_w)
        grid.setVerticalSpacing(2); grid.setContentsMargins(4,4,4,4)
        grid.addWidget(QtWidgets.QLabel("起始能量 (eV)"),1,0); grid.addWidget(self.spn_ev_start,2,0)
        grid.addWidget(QtWidgets.QLabel("結束能量 (eV)"),1,1); grid.addWidget(self.spn_ev_end,2,1)
        grid.addWidget(QtWidgets.QLabel("掃描間距 (eV)"),1,2); grid.addWidget(self.spn_ev_step,2,2)
        grid.addWidget(QtWidgets.QLabel("掃描次數"),1,3);      grid.addWidget(self.spn_repeat,2,3)
        grid.addWidget(QtWidgets.QLabel("起始波長 (nm)"),3,0); grid.addWidget(self.spn_wl_start,4,0)
        grid.addWidget(QtWidgets.QLabel("結束波長 (nm)"),3,1); grid.addWidget(self.spn_wl_end,4,1)
        grid.addWidget(QtWidgets.QLabel("每幾次自動存檔?"),3,2); grid.addWidget(self.spn_save_every,4,2)
        grid.addWidget(QtWidgets.QLabel("保留自動存檔數量"),3,3);     grid.addWidget(self.spn_keep_files,4,3)
        row = 5
        grid.addWidget(QtWidgets.QLabel("目標波長 (nm)"), row,0); grid.addWidget(self.spn_wl_set,row+1,0)
        grid.addWidget(QtWidgets.QLabel("目標能量 (eV)"), row,1); grid.addWidget(self.spn_ev_set,row+1,1)
        grid.addWidget(QtWidgets.QLabel("移動至目標波長"),     row,2); grid.addWidget(self.btn_goto,row+1,2)
        grid.addWidget(QtWidgets.QLabel("計數器位置"),     row,3); grid.addWidget(self.spn_idx_now,row+1,3)
        # 按鈕列
        btn_row = QtWidgets.QHBoxLayout(); btn_row.addStretch();
        for b in (self.btn_save,self.btn_load,self.btn_sel_dir,self.lbl_dir): btn_row.addWidget(b)
        btn_row.addStretch(); grid.addLayout(btn_row,0,0,1,4)
        param_w.setFixedHeight(190); param_w.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Fixed)

        # ---- 儲存路徑顯示 ----
        row_start = QtWidgets.QHBoxLayout()
        row_start.addStretch(); row_start.addWidget(self.btn_start);row_start.addWidget(self.btn_resume); row_start.addStretch()
        row_start.insertWidget(1, self.btn_autocheck)   # 就放在開始掃描左側
        
        # ---- 主垂直版面 ----
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.addWidget(param_w)
        vbox.addLayout(row_start)
        self.canvas_avg = FigureCanvas(Figure(figsize=(4,2.5)))
        self.ax_avg = self.canvas_avg.figure.add_subplot(111)
        vbox.addWidget(self.canvas_avg)

        # 事件連線
        self.btn_start.clicked.connect(self.start_scan)
        self.btn_save .clicked.connect(self.save_data_dialog)
        self.btn_load .clicked.connect(self.load_avg_file)
        self.btn_sel_dir.clicked.connect(self.choose_save_dir)
        self.btn_resume.clicked.connect(self.resume_scan)

        self.spn_ev_start.valueChanged.connect(self.update_from_energy)
        self.spn_ev_end  .valueChanged.connect(self.update_from_energy)
        self.spn_wl_start.valueChanged.connect(self.update_from_wavelength)
        self.spn_wl_end  .valueChanged.connect(self.update_from_wavelength)

        self.btn_autocheck.clicked.connect(self.auto_check)
        self.btn_goto.clicked.connect(self.goto_target)
        self.motor.positionChanged.connect(self.spn_idx_now.setValue)
        self.spn_idx_now.editingFinished.connect(
            lambda: setattr(self.motor, "position", self.spn_idx_now.value())
        )


        
        # 進度條：顯示 idx 或百分比
        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setRange(0, 100)              # 0-100 %
        self.pbar.setValue(0)
        self.pbar.setTextVisible(True)
        vbox.addWidget(self.pbar)               # 加在平均小圖下面

        #馬達單位換算
        self.spn_wl_set.valueChanged.connect(
            lambda v: self.spn_ev_set.setValue(1239.84193/v))
        self.spn_ev_set.valueChanged.connect(
            lambda v: self.spn_wl_set.setValue(1239.84193/v))

    def goto_target(self):
        # 1) 檢查「目前計數器」是否輸入
        if self.spn_idx_now.value() == 0 and not hasattr(self, "_idx_known"):
            QtWidgets.QMessageBox.warning(self, "未知計數器", "請先輸入目前計數器位置！")
            return
        # 2) 校正表是否存在
        if self.cal_table is None:
            QtWidgets.QMessageBox.warning(self, "未載入校正", "請先到『馬達校正』分頁載入校正檔")
            return
        # 3) λ/eV → idx_user → idx_phys (校正)
        lam_target = self.spn_wl_set.value()
        idx_target = int(round(self.mapper.idx_from_nm(lam_target)))
        self._goto_with_progress(idx_target)

    def _goto_with_progress(self, pulse_target):
        pulse_now = self.motor.position
        steps = abs(pulse_target - pulse_now)
        if steps == 0: return
        step = 1 if pulse_target > pulse_now else -1
        for _ in range(steps):
            pulse_now += step
            self.motor.goto(pulse_now)
            
    @QtCore.pyqtSlot(list)
    def set_calibration(self, tbl_nm_phys):
        ev_s, step = self.spn_ev_start.value(), self.spn_ev_step.value()
        tbl = []
        for nm, phys in tbl_nm_phys:
            ev = 1239.84193 / nm
            user_idx = int(round((ev - ev_s) / step))
            tbl.append((user_idx, phys))
        self.cal_table = sorted(tbl, key=lambda t: t[0])
            
    # -------------------------------------------------
    # 單位換算
    # -------------------------------------------------
    def update_from_energy(self):
        self.spn_wl_start.blockSignals(True); self.spn_wl_end.blockSignals(True)
        self.spn_wl_start.setValue(1239.84193/self.spn_ev_start.value())
        self.spn_wl_end.setValue(1239.84193/self.spn_ev_end.value())
        self.spn_wl_start.blockSignals(False); self.spn_wl_end.blockSignals(False)

    def update_from_wavelength(self):
        self.spn_ev_start.blockSignals(True); self.spn_ev_end.blockSignals(True)
        self.spn_ev_start.setValue(1239.84193/self.spn_wl_start.value())
        self.spn_ev_end.setValue(1239.84193/self.spn_wl_end.value())
        self.spn_ev_start.blockSignals(False); self.spn_ev_end.blockSignals(False)

    # -------------------------------------------------
    # 掃描控制
    # -------------------------------------------------
    def start_scan(self) -> None:
        ev_s = self.spn_ev_start.value()
        ev_e = self.spn_ev_end.value()
        step = self.spn_ev_step.value() or 0.01
        if ev_e < ev_s and step > 0:
            step = -step
        ev_arr = np.arange(ev_s, ev_e + step / 2, step)
        if ev_arr.size == 0:
            QtWidgets.QMessageBox.warning(self, "步距錯誤", "請確認起迄能量與步距")
            return

        lam_arr = 1239.84193 / ev_arr      # eV → nm
        idx_arr = [int(round(self.mapper.idx_from_nm(l))) for l in lam_arr] 
        repeat = self.spn_repeat.value()

        self.worker = ScanWorker(self.lockin, self.motor, idx_arr, ev_arr, repeat, self)
        self.worker.point_ready.connect(self.on_point)
        self.worker.run_complete.connect(self.on_run_complete)
        self.worker.finished.connect(self.on_worker_finish)
        self.worker.start()

    def stop_scan(self):
        if hasattr(self,"worker") and self.worker.isRunning():
            self.worker.requestInterruption(); self.worker.wait()
        self.btn_start.setEnabled(True); self.live_widget.btn_stop.setEnabled(False)
        self.live_widget.reset_plot()
        self._switch_to_ctrl_and_load()

    def resume_scan(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            return  # 正在掃描
        if not self.current_ev:
            QtWidgets.QMessageBox.information(self, "無可續掃", "請先停止於中途的掃描")
            return

        ev_left = np.array(self.current_ev)
        repeat_left = self.spn_repeat.value() - len(self.completed_runs)
        if repeat_left <= 0:
            QtWidgets.QMessageBox.information(self, "已完成", "無剩餘掃描")
            return

        self.live_widget.start_new_run()
        for w in self._ctrl_widgets:
            w.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.live_widget.btn_stop.setEnabled(True)
        self.btn_resume.setEnabled(False)

        self.worker = ScanWorker(self.lockin, self.motor, ev_left, repeat_left, self)
        self.worker.point_ready.connect(self.on_point)
        self.worker.run_complete.connect(self.on_run_complete)
        self.worker.finished.connect(self.on_worker_finish)
        self.worker.start()
        self.tab_widget.setCurrentWidget(self.live_widget)

    def auto_check(self):
        ev_s = self.spn_ev_start.value()
        ev_e = self.spn_ev_end.value()
        step = self.spn_ev_step.value() or 0.01
        idx0 = 0
        idx1 = int(round((ev_e - ev_s) / step))
        self.workerAC = AutoCheckWorker(self.motor, idx0, idx1)
        self.workerAC.progress.connect(self.pbar.setValue)
        self.workerAC.finished.connect(self._ac_done)
        self.workerAC.start()
        
    def _ac_done(self, msg):
        self._lock_ctrl(False)
        self.pbar.setValue(0)
        if msg:
            QtWidgets.QMessageBox.critical(self,"Auto-Check 失敗",msg)
        else:
            QtWidgets.QMessageBox.information(self,"Auto-Check","完成")

    def _lock_ctrl(self, on):
        for w in self._ctrl_widgets+[self.btn_start,self.btn_resume,self.btn_autocheck]:
            w.setEnabled(not on)
        self.live_widget.btn_stop.setEnabled(not on)
        
    # -------------------------------------------------
    # 執行緒信號
    # -------------------------------------------------
    def on_point(self, ev, x_n, y_n, edc):
        self.current_ev.append(ev); self.current_x.append(x_n); self.current_y.append(y_n)
        # 傳給圖頁
        self.live_widget.point_updated.emit(ev,x_n,y_n,edc)

    def on_run_complete(self, ev_arr, x_arr, y_arr):
        # 保存本輪資料
        self.completed_runs.append((np.asarray(ev_arr), x_arr, y_arr))
        # 更新平均線
        self.live_widget.update_average(self.completed_runs)
        # 累積待存
        self.pending_runs.append((ev_arr, x_arr, y_arr))
        if len(self.pending_runs) >= self.spn_save_every.value():
            self._save_average_file(); self.pending_runs.clear()
        # 通知圖頁下一輪 live 線
        self.live_widget.start_new_run()

    def on_worker_finish(self):
        self.btn_start.setEnabled(True); self.live_widget.btn_stop.setEnabled(False)
        self._switch_to_ctrl_and_load()

    def _switch_to_ctrl_and_load(self):
        """跳回控制分頁，並把最新平均畫到小圖"""
        self.scan_finished.emit()  # _switch_to_ctrl_and_load 內
        # ① 找到 QTabWidget
        tab = self.parentWidget()
        while tab and not isinstance(tab, QtWidgets.QTabWidget):
            tab = tab.parentWidget()
        if tab:
            tab.setCurrentWidget(self)          # 切到控制分頁

        # ② 把最新平均畫到 ax_avg
        if self.completed_runs:
            ev, xs, ys = self.completed_runs[-1]
            self.ax_avg.clear()
            self.ax_avg.plot(ev, xs, "--b", label="X/EDC")
            self.ax_avg.plot(ev, ys, "--r", label="Y/EDC")
            self.ax_avg.legend(); self.ax_avg.grid(True)
            self.ax_avg.relim(); self.ax_avg.autoscale_view()
            self.canvas_avg.draw_idle()
        for w in self._ctrl_widgets:
            w.setEnabled(True)
        self.btn_resume.setEnabled(True)       # 只有暫停時才亮


    # -------------------------------------------------
    # 檔案 I/O
    # -------------------------------------------------
    def _save_average_file(self):
        """把 pending_runs 求平均後寫成 .asc，並做 FIFO 刪檔"""
        if not self.pending_runs:
            return
        ev = self.pending_runs[0][0]
        xs = np.vstack([d[1] for d in self.pending_runs])
        ys = np.vstack([d[2] for d in self.pending_runs])
        x_m = xs.mean(axis=0); y_m = ys.mean(axis=0)

        # 批次計數器 → 檔名 = 掃描次數 .asc
        self.batch_counter += 1
        N = self.spn_save_every.value()
        scans_done = self.batch_counter * N
        fname = f"{scans_done}.asc"
        fpath = os.path.join(self.save_dir, fname)

        # 二欄區塊：energy X/EDC ；空行；energy Y/EDC
        lines = ["energy\tX/EDC\n"]
        for e, x in zip(ev, x_m):
            lines.append(f"{e:.6e}\t{x:.6e}\n")
        lines.append("\n")
        lines.append("energy\tY/EDC\n")
        for e, y in zip(ev, y_m):
            lines.append(f"{e:.6e}\t{y:.6e}\n")
        with open(fpath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"[SAVE] {fpath}")

        # FIFO 刪舊檔
        self.saved_files.append(fpath)
        M = self.spn_keep_files.value()
        while len(self.saved_files) > M:
            old = self.saved_files.popleft()
            try:
                os.remove(old); print(f"[DEL ] {old}")
            except FileNotFoundError:
                pass

    def save_data_dialog(self):
        """手動把目前平均寫檔 (.asc)"""
        if not self.completed_runs:
            QtWidgets.QMessageBox.warning(self, "尚無資料", "請先完成至少一次掃描"); return
        ev, xs, ys = self.completed_runs[-1]
        fn, _ = QFileDialog.getSaveFileName(self, "另存平均檔", "avg.asc", "ASC Files (*.asc)")
        if not fn:
            return
        lines = ["energy\tX/EDC\n"]
        for e, x in zip(ev, xs): lines.append(f"{e:.6e}\t{x:.6e}\n")
        lines.append("\n")
        lines.append("energy\tY/EDC\n")
        for e, y in zip(ev, ys): lines.append(f"{e:.6e}\t{y:.6e}\n")
        with open(fn, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def choose_save_dir(self):
        new_dir = QFileDialog.getExistingDirectory(self, "選擇自動存檔資料夾", self.save_dir)
        if new_dir:
            self.save_dir = new_dir; os.makedirs(self.save_dir, exist_ok=True)
            self.lbl_dir.setText(self.save_dir)

    def load_avg_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "選擇 .asc 平均檔", "", "ASC Files (*.asc)")
        if not fn: return
        ev, x_avg, y_avg = self._read_avg_asc(fn)
        self.ax_avg.clear()
        self.ax_avg.plot(ev, x_avg, "--b", label="X/EDC")
        self.ax_avg.plot(ev, y_avg, "--r", label="Y/EDC")
        self.ax_avg.set_xlabel("Energy (eV)")
        self.ax_avg.set_ylabel("ΔR/R")
        self.ax_avg.legend(); self.ax_avg.grid(True)
        self.ax_avg.relim()           # 重新計算資料界限
        self.ax_avg.autoscale_view()  # 依界限自動縮放
        self.canvas_avg.draw_idle()

    @staticmethod
    def _read_avg_asc(fn):
        ev=[]; x=[]; y=[]; mode=0
        with open(fn, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln: continue
                if ln.startswith("energy") and "X" in ln: mode=1; continue
                if ln.startswith("energy") and "Y" in ln: mode=2; continue
                e,v = map(float, ln.split())
                if mode==1: ev.append(e); x.append(v)
                elif mode==2: y.append(v)
        return np.asarray(ev), np.asarray(x), np.asarray(y)
  