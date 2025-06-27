# ---------------------- 依賴檢查 ----------------------
def ensure_dependencies():
    import importlib.util, subprocess, sys
    REQUIRED_MODULES = [
        ("PyQt5", "PyQt5"),
        ("pyvisa", "pyvisa"),
        ("pyvisa_py", "pyvisa-py"),
        ("serial","pyserial"),
        ("matplotlib", "matplotlib")
    ]
    missing = []
    for modname, pipname in REQUIRED_MODULES:
        if importlib.util.find_spec(modname) is None:
            missing.append(pipname)

    if missing:
        print(f"🛠 檢查到缺少套件：{missing}，正在安裝...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("✅ 套件安裝完成，請重新啟動程式。")
        except Exception as e:
            print("❌ 套件安裝失敗，請手動安裝：", missing)
            print("錯誤詳情：", e)
        sys.exit(0)
      
ensure_dependencies()

from abc import ABC, abstractmethod
import math, time, sys, argparse, pathlib
import pyvisa
import numpy as np
from PyQt5 import QtCore, QtWidgets
from PyQt5 import QtGui
import time
from collections import deque, defaultdict
import os, datetime
from PyQt5.QtWidgets import QFileDialog
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from motor import MotorArduino
from mapper import Mapper
from types import MappingProxyType               # 只需一次即可

__all__ = ["ExperimentWidget", "ScanWorker", "LivePlotWidget"]

##################################################
# 1. Lock-in 抽象層
##################################################
class LockInBase(ABC):
    @abstractmethod
    def set_param(self, **kwargs):...
    @abstractmethod
    def read_xyz(self):...
    @abstractmethod
    def name(self):...

##################################################
# 2. NF 5610B 驅動 (沿用 v1.0)
##################################################
class LockInNF5610B(LockInBase):
    _F_RANGE = {"0.5–12 Hz":0, "10–120 Hz":1, "100–1.2 kHz":2, "1–12 kHz":3, "10–200 kHz":4}
    _REF_MODE   = {"INT_F":0,"INT_2F":1,"EXT_F":2,"EXT_2F":3}
    _SENS       = {"100 nV":-2,"300 nV":-1,"1 µV":0,"3 µV":1,"10 µV":2,"30 µV":3,
                   "100 µV":4,"300 µV":5,"1 mV":6,"3 mV":7,"10 mV":8,"30 mV":9,
                   "100 mV":10,"300 mV":11,"1 V":12}
    _TIME_CONST = {"0.1 ms":0,"3 ms":1,"10 ms":2,"30 ms":3,"100 ms":4,
                   "300 ms":5,"1 s":6,"3 s":7,"10 s":8,"30 s":9}
    _FMO = {"THRU":0,"HPF":1,"LPF":2,"NORMAL Q1":30,"NORMAL Q5":31,"NORMAL Q30":32,
            "LPF Q1":33,"LPF Q5":34,"LPF Q30":35,"LPF Q1B":36,"LPF Q5B":37,"LPF Q30B":38}
    _FRQ_RANGE = {
        "0.5-12 Hz":1,
        "10-120 Hz":1, 
        "100-1200 Hz": 2,
        "1-12 kHz": 3,
        "10-120 kHz": 4
    }
    def __init__(self, resource="GPIB0::2::INSTR", timeout_ms=5000):
        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource(resource)
        self.inst.timeout = timeout_ms
        self.inst.write("OSS1;ODS47,4")

    def set_param(self, **kw):
        cmd=[]
        g=kw.get
        if g("f_range") is not None:cmd.append(f"BFR{g('f_range')}")
        if g('ref_mode'):cmd.append(f"BRM{self._REF_MODE[g('ref_mode')]}")
        if g('sensitivity'):cmd.append(f"BSS{self._SENS[g('sensitivity')]}")
        if g('time_const'):cmd.append(f"BTC{self._TIME_CONST[g('time_const')]}")
        if g('filter_mode'):cmd.append(f"FMO{self._FMO[g('filter_mode')]}")
        if g('filter_freq') is not None:
            cmd.append(f"FRQ{int(g('filter_freq'))},{self._FRQ_RANGE[g('filter_freq_range')]}")
        if g('int_osc_freq') is not None:
            cmd.append(f"OFQ{int(g('int_osc_freq'))},{g('int_osc_range') + 1}")
        if g('int_osc_level') is not None:
            cmd.append(f"OLV{int(g('int_osc_level'))},{g('int_osc_level_range')}")
        for c in cmd:
            self.inst.write(c)
        # ★ 新增：固定送 DDT434
        self.inst.write("DDT434")

    def read_xyz(self):
        x,y,e=map(float,self.inst.query("?ODT").strip().split(','));return x,y,e
    def name(self):return "NF 5610B"

##################################################
# 3. Dummy Lock‑in (離線模式)
##################################################
class LockInDummy(LockInBase):
    def __init__(self, logfile="dummy_lockin.log"):
        self.log=open(logfile,'a',encoding='utf8')
    def set_param(self, **kw):
        # 把 NF-5610B 的指令生成規則複製過來
        nf = LockInNF5610B
        maps = {                 # 用 MappingProxyType 防意外修改
            'ref_mode'   : MappingProxyType(nf._REF_MODE),
            'sensitivity': MappingProxyType(nf._SENS),
            'time_const' : MappingProxyType(nf._TIME_CONST),
            'filter_mode': MappingProxyType(nf._FMO),
            'filter_freq_range': MappingProxyType(nf._FRQ_RANGE),
        }
        cmd = []
        g = kw.get
        if g('f_range')       is not None: cmd.append(f"BFR{g('f_range')}")
        if g('ref_mode')      : cmd.append(f"BRM{maps['ref_mode'][g('ref_mode')]}")
        if g('sensitivity')   : cmd.append(f"BSS{maps['sensitivity'][g('sensitivity')]}")
        if g('time_const')    : cmd.append(f"BTC{maps['time_const'][g('time_const')]}")
        if g('filter_mode')   : cmd.append(f"FMO{maps['filter_mode'][g('filter_mode')]}")
        if g('filter_freq') is not None:
            rng = g('filter_freq_range')
            cmd.append(f"FRQ{int(g('filter_freq'))},{maps['filter_freq_range'][rng]}")
        if g('int_osc_freq')  is not None:
            cmd.append(f"OFQ{int(g('int_osc_freq'))},{g('int_osc_range') + 1}")
        if g('int_osc_level') is not None:
            cmd.append(f"OLV{int(g('int_osc_level'))},{g('int_osc_level_range')}")

        line = ";".join(cmd) or "—"
        self.log.write(line + "\n")
        print("[DUMMY   ]", line)
    def read_xyz(self):
        t=time.time();x=1e-3*math.sin(t);y=1e-3*math.cos(t);return x,y,1.0
    def name(self):return "Dummy (Offline)"

##################################################
# 4. GUI元件：Lock‑in Parameter Widget
##################################################
class LockInParamWidget(QtWidgets.QGroupBox):
    def __init__(self, lockin: LockInBase, parent=None):
        super().__init__("Lock-in 參數設定", parent)
        self.lockin = lockin
        nf = LockInNF5610B
        form = QtWidgets.QFormLayout(self)

        ref_keys = list(nf._REF_MODE.keys())
        sens_keys = list(nf._SENS.keys())
        tc_keys = list(nf._TIME_CONST.keys())
        fmo_keys = list(nf._FMO.keys())
        frng_keys = list(nf._FRQ_RANGE.keys())
        frng2_keys = list(nf._F_RANGE.keys()) # for F Range
        olv_ranges = ["0–25.5 mV", "0–255 mV", "0–2.55 V"]

        self.cmb_frange = QtWidgets.QComboBox(); self.cmb_frange.addItems(frng2_keys)
        self.cmb_ref = QtWidgets.QComboBox(); self.cmb_ref.addItems(ref_keys)
        self.cmb_sens = QtWidgets.QComboBox(); self.cmb_sens.addItems(sens_keys)
        self.cmb_tc = QtWidgets.QComboBox(); self.cmb_tc.addItems(tc_keys)
        self.cmb_fmode = QtWidgets.QComboBox(); self.cmb_fmode.addItems(fmo_keys)

        self.spn_ffreq = QtWidgets.QSpinBox()
        self.spn_ffreq.setRange(5, 1200)
        self.cmb_ffrng = QtWidgets.QComboBox(); self.cmb_ffrng.addItems(frng_keys)
        self.lbl_ffval = QtWidgets.QLabel()
        ff_l = QtWidgets.QHBoxLayout(); ff_l.addWidget(self.spn_ffreq); ff_l.addWidget(self.cmb_ffrng); ff_l.addWidget(self.lbl_ffval)
        ff_w = QtWidgets.QWidget(); ff_w.setLayout(ff_l)

        self.spn_ofq = QtWidgets.QSpinBox()
        self.cmb_ofq_rng = QtWidgets.QComboBox(); self.cmb_ofq_rng.addItems(frng_keys)
        self.lbl_ofqval = QtWidgets.QLabel()
        ofq_l = QtWidgets.QHBoxLayout(); ofq_l.addWidget(self.spn_ofq); ofq_l.addWidget(self.cmb_ofq_rng); ofq_l.addWidget(self.lbl_ofqval)
        ofq_w = QtWidgets.QWidget(); ofq_w.setLayout(ofq_l)

        self.spn_olv = QtWidgets.QSpinBox()
        self.cmb_olv_rng = QtWidgets.QComboBox(); self.cmb_olv_rng.addItems(olv_ranges)
        self.lbl_olvval = QtWidgets.QLabel()
        olv_l = QtWidgets.QHBoxLayout(); olv_l.addWidget(self.spn_olv); olv_l.addWidget(self.cmb_olv_rng); olv_l.addWidget(self.lbl_olvval)
        olv_w = QtWidgets.QWidget(); olv_w.setLayout(olv_l)
        self.spn_olv.setRange(0, 255)

        self.chk_safe = QtWidgets.QCheckBox("啟用安全漸進 OLV")

        self.btn_apply = QtWidgets.QPushButton("套用參數")

        # -- 預設值 --
        self.cmb_frange.setCurrentIndex(2)   # 100~1.2 k
        self.cmb_ref   .setCurrentIndex(0)   # INT_F
        self.cmb_sens  .setCurrentIndex(10)   # 10 mV
        self.cmb_tc    .setCurrentIndex(6)   # 1 s
        self.cmb_fmode .setCurrentIndex(5)  # Normal Q30
        self.spn_ffreq.setValue(400); self.cmb_ffrng.setCurrentIndex(2)
        self.spn_ofq .setValue(40); self.cmb_ofq_rng.setCurrentIndex(0)
        self.spn_olv .setValue(0); self.cmb_olv_rng.setCurrentIndex(2)
        self.chk_safe.setChecked(True)

        form.addRow("F Range", self.cmb_frange)
        form.addRow("Ref Mode", self.cmb_ref)
        form.addRow("Sensitivity", self.cmb_sens)
        form.addRow("Time Constant", self.cmb_tc)
        form.addRow("Filter Mode", self.cmb_fmode)
        form.addRow("Filter Freq / Range", ff_w)
        form.addRow("INT OSC Freq / Range", ofq_w)
        form.addRow("INT OSC Level / Range", olv_w)
        form.addRow(self.chk_safe)
        form.addRow(self.btn_apply)

        self.btn_apply.clicked.connect(self._apply)
        for w in [self.cmb_ref, self.cmb_sens, self.cmb_tc, self.cmb_fmode,
                  self.spn_ffreq, self.cmb_ffrng, self.spn_ofq, self.cmb_ofq_rng,
                  self.spn_olv, self.cmb_olv_rng, self.cmb_frange]:
            (w.currentIndexChanged if isinstance(w, QtWidgets.QComboBox) else w.valueChanged).connect(self._on_change)

    def _on_change(self):
        def frq_factor(code): return [0.01, 0.1, 1, 10, 100][code]
        def ofq_factor(code): return [0.1,1,10,100][code]
        def olv_factor(code): return [0.0001,0.001,0.01][code]

        idx1 = self.cmb_ffrng.currentIndex()
        idx2 = self.cmb_ofq_rng.currentIndex()
        idx3 = self.cmb_olv_rng.currentIndex()

        self.spn_ffreq.setMinimum(5 if idx1==0 else 10)
        self.spn_ffreq.setMaximum(1200)
        self.spn_ofq.setMinimum(5); self.spn_ofq.setMaximum(1200)

        val1 = self.spn_ffreq.value()
        val2 = self.spn_ofq.value()
        val3 = self.spn_olv.value()

        real1 = val1 * frq_factor(idx1)
        real2 = val2 * ofq_factor(idx2)
        real3 = val3 * olv_factor(idx3)

        self.lbl_ffval.setText(f"→ {real1:.2f} Hz" if real1 < 1000 else f"→ {real1/1000:.2f} kHz")
        self.lbl_ofqval.setText(f"→ {real2:.2f} Hz" if real2 < 1000 else f"→ {real2/1000:.2f} kHz")
        self.lbl_olvval.setText(f"→ {real3*1000:.1f} mV" if real3 < 0.1 else f"→ {real3:.3f} V")

        valid1 = val1 >= (5 if idx1 == 0 else 10)
        valid2 = val2 >= (5 if idx2 == 0 else 100)
        valid3 = real3 <= [0.0255, 0.255, 2.55][idx3]

        self.spn_ffreq.setStyleSheet("" if valid1 else "background:#ffcccc;")
        self.spn_ofq.setStyleSheet("" if valid2 else "background:#ffcccc;")
        self.spn_olv.setStyleSheet("" if valid3 else "background:#ffcccc;")

        self.btn_apply.setEnabled(valid1 and valid2 and valid3)

    def _apply(self):
        f_range_idx = self.cmb_frange.currentIndex()
        params = dict(
            f_range = f_range_idx,
            ref_mode=self.cmb_ref.currentText(),
            sensitivity=self.cmb_sens.currentText(),
            time_const=self.cmb_tc.currentText(),
            filter_mode=self.cmb_fmode.currentText(),
            filter_freq=self.spn_ffreq.value(),
            filter_freq_range=self.cmb_ffrng.currentText(),
            int_osc_freq=self.spn_ofq.value(),
            int_osc_range=self.cmb_ofq_rng.currentIndex(),
            int_osc_level_range=self.cmb_olv_rng.currentIndex(),
        )
        target = self.spn_olv.value()
        params["int_osc_level"] = target

        safe = self.chk_safe.isChecked()

        try:
            if safe and hasattr(self, "_olv_last"):
                start = self._olv_last
                for i in range(1, 11):
                    v = round(start + (target - start) * i / 10)
                    self.lockin.set_param(int_osc_level=v, int_osc_level_range=params["int_osc_level_range"])
                    QtWidgets.QApplication.processEvents()
                    time.sleep(1)
                self.lockin.set_param(**params)
            else:
                self.lockin.set_param(**params)
            self._olv_last = target
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Set-param Error", str(e))

##################################################
# 5. GUI元件：實驗模式分頁
##################################################
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
        self.spn_idx_now.setValue(0)
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
        grid.addWidget(QtWidgets.QLabel("目前計數器"),     row,3); grid.addWidget(self.spn_idx_now,row+1,3)
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
        pulse_target = self.mapper.pulse_from_nm(lam_target)
        self._goto_with_progress(pulse_target)

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
        pulse_arr = [self.mapper.pulse_from_nm(l) for l in lam_arr]
        repeat = self.spn_repeat.value()

        self.worker = ScanWorker(self.lockin, self.motor, pulse_arr, ev_arr, repeat, self)
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
  
##################################################
# 6.ScanWorker
##################################################
class ScanWorker(QtCore.QThread):
    """Background scan: move motor → 讀 lock-in → emit data"""

    point_ready = QtCore.pyqtSignal(float, float, float, float)   # ev, x/edc, y/edc, edc
    run_complete = QtCore.pyqtSignal(object, object, object)      # ev_arr, x_arr, y_arr

    def __init__(self, lockin, motor, pulse_arr, ev_arr, repeat: int, ui_widget):
        super().__init__()
        self.lockin = lockin
        self.motor = motor
        self.pulse_arr = pulse_arr
        self.ev_arr = ev_arr
        self.repeat = repeat
        self.ui = ui_widget

    def run(self) -> None:
        for _ in range(self.repeat):
            if self.isInterruptionRequested():
                return
            xs, ys = [], []
            for pulse, ev in zip(self.pulse_arr, self.ev_arr):
                self.motor.goto(pulse)
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
        
##################################################
# 8. GUI 元件：LivePlotWidget — 專責即時/平均繪圖
##################################################
class LivePlotWidget(QtWidgets.QWidget):
    """僅顯示即時掃描曲線與平均/載入檔。無控制元件。"""

    point_updated = QtCore.pyqtSignal(float, float, float, float)  # ev, x, y, edc

    def __init__(self, parent=None):
        super().__init__(parent)
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        self.canvas = FigureCanvas(Figure(figsize=(5, 3)))
        self.ax = self.canvas.figure.add_subplot(111)
        self.ax.set_xlabel("Energy (eV)")
        self.ax.set_ylabel("ΔR/R")
        self.ax.grid(True)

        self.lbl_status = QtWidgets.QLabel("X=…   Y=…   EDC=…")
        self.lbl_status.setAlignment(QtCore.Qt.AlignRight)
        self.run_idx   = 0      # 第幾次掃描
        self.point_idx = 0      # 目前點序
        self.total_runs = 0        # 由控制頁在 start_scan() 設定
        self.total_pts  = 0

        self.btn_stop = QtWidgets.QPushButton("停止掃描")
        self.btn_stop.setEnabled(False)           # 掃描時啟用

        vbox = QtWidgets.QVBoxLayout(self)
        vbox.addWidget(self.canvas)
        footer = QtWidgets.QWidget()
        hbox   = QtWidgets.QHBoxLayout(footer)
        hbox.setContentsMargins(4, 0, 4, 0)
        hbox.addWidget(self.lbl_status)
        hbox.addStretch()
        hbox.addWidget(self.btn_stop)
        footer.setFixedHeight(28)
        footer.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                             QtWidgets.QSizePolicy.Fixed)
        vbox.addWidget(footer)

        # 初始線條
        self.line_live_x = None
        self.line_live_y = None
        self.line_avg_x  = None
        self.line_avg_y  = None

        # 連接即時點訊號
        self.point_updated.connect(self.on_point)

    # ---------------- 繪圖 API ----------------
    def reset_plot(self):
        """外部在每次 Start 之前呼叫，清空整張圖。"""
        self.ax.clear()
        self.ax.set_xlabel("Energy (eV)")
        self.ax.set_ylabel("ΔR/R")
        self.ax.grid(True)
        self.line_live_x = self.line_live_y = None
        self.line_avg_x  = self.line_avg_y  = None
        self.run_idx = 0
        self.point_idx = 0
        self.canvas.draw_idle()

    def start_new_run(self):
        self.run_idx  += 1      # 每輪 +1
        self.point_idx = 0      # 重置點序
        """凍結現行 live 為虛線，並建立新的 live 線。"""
        if self.line_live_x is not None:
            self.line_live_x.remove(); self.line_live_y.remove()

        # 建立新的 live 線
        self.line_live_x, = self.ax.plot([], [], color="blue", label="X/EDC")
        self.line_live_y, = self.ax.plot([], [], color="red",  label="Y/EDC")
        self.ax.legend(loc="upper right")
        self.canvas.draw_idle()

    @QtCore.pyqtSlot(float, float, float, float)
    def on_point(self, ev, x_n, y_n, edc):
        """即時更新目前 live 線。"""
        if self.line_live_x is None:
            self.start_new_run()
        # 更新線條資料
        xs = np.append(self.line_live_x.get_xdata(), ev)
        ys = np.append(self.line_live_x.get_ydata(), x_n)
        self.line_live_x.set_data(xs, ys)
        ys2 = np.append(self.line_live_y.get_ydata(), y_n)
        self.line_live_y.set_data(xs, ys2)
        # 重設座標範圍
        self.ax.relim(); self.ax.autoscale_view()
        # 更新右上角數值
        self.point_idx += 1
        self.lbl_status.setText(f"Scan {self.run_idx}/{self.total_runs}  Point {self.point_idx}/{self.total_pts}   "f"X={x_n:.3e}   Y={y_n:.3e}   EDC={edc:.3e}")
        self.canvas.draw_idle()

    def update_average(self, runs):
        """runs = [(ev_arr, x_arr, y_arr), …] → 畫/更新平均虛線"""
        if not runs:
            return
        ev_ref = runs[0][0]
        xs = np.vstack([d[1] for d in runs])
        ys = np.vstack([d[2] for d in runs])
        x_avg = xs.mean(axis=0)
        y_avg = ys.mean(axis=0)
        if self.line_avg_x is None:
            self.line_avg_x, = self.ax.plot(ev_ref, x_avg, "--", color="cyan", label="X/EDC avg")
            self.line_avg_y, = self.ax.plot(ev_ref, y_avg, "--", color="magenta", label="Y/EDC avg")
        else:
            self.line_avg_x.set_data(ev_ref, x_avg)
            self.line_avg_y.set_data(ev_ref, y_avg)
        self.ax.legend(loc="upper right"); self.canvas.draw_idle()

    def plot_avg_from_file(self, ev, x_avg, y_avg):
        """將載入的平均檔畫成灰色虛線。"""
        self.ax.plot(ev, x_avg, "--", color="gray", label="X/EDC file")
        self.ax.plot(ev, y_avg, "--", color="gray", label="Y/EDC file")
        self.ax.legend(loc="upper right"); self.canvas.draw_idle()

##################################################
# 9. 馬達校正
##################################################
class CalibrationWidget(QtWidgets.QWidget):
    """手動建立 / 載入校正表；支援 jog 微移馬達。"""
    cal_loaded = QtCore.pyqtSignal(list)          # [(nm, phys_idx), …]

    def __init__(self, motor, mapper, parent=None):
        super().__init__(parent)
        self.motor = motor
        self.mapper = mapper
        self.cal_tbl = []                         # 暫存校正點

        # ───── 控件 ─────
        self.spn_nm   = QtWidgets.QDoubleSpinBox(); self.spn_nm.setRange(100,3000); self.spn_nm.setDecimals(1); self.spn_nm.setSingleStep(0.1)
        self.spn_idx_now  = QtWidgets.QSpinBox();      self.spn_idx_now.setRange(0,999)
        self.spn_step = QtWidgets.QDoubleSpinBox(); self.spn_step.setRange(0.1,200); self.spn_step.setDecimals(1); self.spn_step.setValue(1.0)
        self.btn_ccw  = QtWidgets.QPushButton("↺")
        self.btn_cw   = QtWidgets.QPushButton("↻")
        self.btn_add  = QtWidgets.QPushButton("加入校正點")
        self.lst_pts  = QtWidgets.QListWidget()
        self.btn_save = QtWidgets.QPushButton("存成 CSV")
        self.btn_load = QtWidgets.QPushButton("載入校正檔…")

        # ───── 版面 ─────
        g = QtWidgets.QGridLayout(self)
        g.setContentsMargins(4,4,4,4);  g.setVerticalSpacing(2)
        g.addWidget(QtWidgets.QLabel("光譜儀波長 (nm)"), 0,0); g.addWidget(self.spn_nm, 0,1)
        g.addWidget(QtWidgets.QLabel("計數器位置"),       0,2); g.addWidget(self.spn_idx_now,0,3)
        g.addWidget(QtWidgets.QLabel("步距 (nm)"),      1,0); g.addWidget(self.spn_step,1,1)
        g.addWidget(self.btn_ccw, 1,2); g.addWidget(self.btn_cw, 1,3)
        g.addWidget(self.btn_add, 0,4)
        g.addWidget(self.lst_pts, 2,0,1,5)
        g.addWidget(self.btn_save,3,3); g.addWidget(self.btn_load,3,4)

        # ───── 事件 ─────
        self.btn_ccw.clicked.connect(lambda: self.jog(-1))
        self.btn_cw .clicked.connect(lambda: self.jog(+1))
        self.btn_add.clicked.connect(self.add_point)
        self.btn_save.clicked.connect(self.on_save_calib)
        self.btn_load.clicked.connect(self.on_load_calib)
        self.motor.positionChanged.connect(self.spn_idx_now.setValue)
        self.spn_idx_now.editingFinished.connect(
            lambda: setattr(self.motor, "position", self.spn_idx_now.value())
        )


    # ───── 功能 ─────
    def _nm_to_pulse(self, nm_val: float) -> int:
        if len(self.cal_tbl) >= 2:                 # 已有校正 → 用斜率
            xs, ys = zip(*self.cal_tbl)
            slope = (ys[-1]-ys[0])/(xs[-1]-xs[0])  # idx / nm
            return int(round(nm_val * slope))
        return int(round(nm_val))
    
    def jog(self, sign: int):
        if hasattr(self, "worker") and self.worker.isRunning():
            return  # 忙碌中，不接受新指令

        step_nm = self.spn_step.value()

        if len(self.cal_tbl) >= 2:
            pulse_step = self.mapper.pulse_from_nm(step_nm)
        else:
            pulse_step = self._nm_to_pulse(step_nm)

        target_idx = max(0, min(999, self.motor.position + sign * pulse_step))

        self.worker = MotorMoveWorker(self.motor, target_idx, self)
        self.worker.finished.connect(self.spn_idx_now.setValue)
        self.worker.start()
 
    def add_point(self):
        lam_nm  = self.spn_nm.value()
        pulse = self.spn_idx_now.value()
        self.mapper.cal_tbl.append((lam_nm, pulse))
        self.lst_pts.addItem(f"λ = {lam_nm:.1f} nm   →   p = {pulse}")
    
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

    def on_load_calib(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "載入校正檔", "", "CSV (*.csv);;All Files (*)"
        )
        if filename:
            try:
                self.mapper.load(filename)
                QtWidgets.QMessageBox.information(self, "完成", f"已載入 {filename}")
                # 視需要刷新校正表 GUI
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "載入失敗", str(e))

class MotorMoveWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(int)      # 把真正位置回傳給 GUI
    def __init__(self, motor, idx, parent=None):
        super().__init__(parent)
        self.motor = motor
        self.idx = idx

    def run(self):
        self.motor.goto(self.idx)
        self.finished.emit(self.idx)

##################################################
# 10. Main Window
##################################################
class MultiTabMainWindow(QtWidgets.QMainWindow):
    def __init__(self, offline=False):
        super().__init__()
        self.setWindowTitle("熱調製光譜 GUI")
        self.statusBar().showMessage("Initializing…")
        
        self.mapper = Mapper()
        self.motor = MotorArduino()

        if not offline:
            try:
                self.lockin = LockInNF5610B()  
                self.offline = False
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Lock‑in Error", f"無法連接 NF 5610B → 轉離線模式\n{e}")
                self.lockin = LockInDummy()
                self.offline = True
        else:
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
##################################################
# 11. CLI Entry
##################################################
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HeatMod GUI")
    parser.add_argument("--offline", action="store_true", help="強制離線 Dummy 模式")
    args = parser.parse_args()
    app = QtWidgets.QApplication(sys.argv)
    win = MultiTabMainWindow(offline=args.offline)
    win.resize(1200, 800)
    win.show()
    font = QtGui.QFont("Microsoft JhengHei UI", 14)  # ← 字體 + pt 數
    font.setStyleStrategy(QtGui.QFont.PreferAntialias)  # 抗鋸齒
    QtWidgets.QApplication.setFont(font)
    sys.exit(app.exec_())
