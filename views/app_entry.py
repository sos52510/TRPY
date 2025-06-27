from PyQt5 import QtGui, QtWidgets
from views.main_window import MultiTabMainWindow
import sys
import argparse

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
