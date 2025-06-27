import numpy as np
from PyQt5 import QtCore, QtWidgets

##################################################
# 1. Lock-in 抽象層

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
