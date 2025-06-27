import time
from PyQt5 import QtWidgets
from drivers.lockin import LockInNF5610B, LockInBase

##################################################
# 1. Lock-in 抽象層

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
        ofq_keys = list(nf._OFQ_RANGE.keys())
        olv_ranges = ["0–25.5 mV", "0–255 mV", "0–2.55 V"]

        self.cmb_ref = QtWidgets.QComboBox(); self.cmb_ref.addItems(ref_keys)
        self.cmb_sens = QtWidgets.QComboBox(); self.cmb_sens.addItems(sens_keys)
        self.cmb_tc = QtWidgets.QComboBox(); self.cmb_tc.addItems(tc_keys)
        self.cmb_fmode = QtWidgets.QComboBox(); self.cmb_fmode.addItems(fmo_keys)

        self.spn_ofq = QtWidgets.QSpinBox()
        self.cmb_ofq_rng = QtWidgets.QComboBox(); self.cmb_ofq_rng.addItems(ofq_keys)
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
        self.cmb_ref   .setCurrentIndex(0)   # INT_F
        self.cmb_sens  .setCurrentIndex(10)   # 10 mV
        self.cmb_tc    .setCurrentIndex(6)   # 1 s
        self.cmb_fmode .setCurrentIndex(5)  # Normal Q30
        self.spn_ofq .setValue(40); self.cmb_ofq_rng.setCurrentIndex(0)
        self.spn_olv .setValue(0); self.cmb_olv_rng.setCurrentIndex(2)
        self.chk_safe.setChecked(True)

        form.addRow("Ref Mode", self.cmb_ref)
        form.addRow("Sensitivity", self.cmb_sens)
        form.addRow("Time Constant", self.cmb_tc)
        form.addRow("Filter Mode", self.cmb_fmode)
        form.addRow("INT OSC Freq / Range", ofq_w)
        form.addRow("INT OSC Level / Range", olv_w)
        form.addRow(self.chk_safe)
        form.addRow(self.btn_apply)

        self.btn_apply.clicked.connect(self._apply)
        for w in [self.cmb_ref, self.cmb_sens, self.cmb_tc, self.cmb_fmode,
                  self.spn_ofq, self.cmb_ofq_rng,
                  self.spn_olv, self.cmb_olv_rng]:
            (w.currentIndexChanged if isinstance(w, QtWidgets.QComboBox) else w.valueChanged).connect(self._on_change)

    def _on_change(self):
        def ofq_factor(code): return [0.1,1,10,100][code]
        def olv_factor(code): return [0.0001,0.001,0.01][code]

        idx2 = self.cmb_ofq_rng.currentIndex()
        idx3 = self.cmb_olv_rng.currentIndex()

        self.spn_ofq.setMinimum(5); self.spn_ofq.setMaximum(1200)

        val2 = self.spn_ofq.value()
        val3 = self.spn_olv.value()

        real2 = val2 * ofq_factor(idx2)
        real3 = val3 * olv_factor(idx3)

        self.lbl_ofqval.setText(f"→ {real2:.2f} Hz" if real2 < 1000 else f"→ {real2/1000:.2f} kHz")
        self.lbl_olvval.setText(f"→ {real3*1000:.1f} mV" if real3 < 0.1 else f"→ {real3:.3f} V")

        valid2 = val2 >= (5 if idx2 == 0 else 100)
        valid3 = real3 <= [0.0255, 0.255, 2.55][idx3]

        self.spn_ofq.setStyleSheet("" if valid2 else "background:#ffcccc;")
        self.spn_olv.setStyleSheet("" if valid3 else "background:#ffcccc;")

        self.btn_apply.setEnabled(valid2 and valid3)

    def _apply(self):
        params = dict(
            ref_mode=self.cmb_ref.currentText(),
            sensitivity=self.cmb_sens.currentText(),
            time_const=self.cmb_tc.currentText(),
            filter_mode=self.cmb_fmode.currentText(),
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
