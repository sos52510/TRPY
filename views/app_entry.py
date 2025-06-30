# ---------------------- 依賴檢查 ----------------------
# utils/dependencies.py
import sys
import os

def ensure_dependencies():
    # 如果已經是打包後的 .exe，直接跳過檢查
    if getattr(sys, "frozen", False):
        return

    # 開發階段才檢查 / 安裝
    import importlib.util, subprocess
    REQUIRED = ["PyQt5", "pyvisa", "serial", "matplotlib"]
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if missing:
        print("缺少套件，正在安裝：", ", ".join(missing))
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("✅ 安裝完成，請重新執行程式。")
        except subprocess.CalledProcessError as e:
            print("❌ 自動安裝失敗，請手動 pip install →", ", ".join(missing))
        sys.exit(1)
      
ensure_dependencies()

from PyQt5 import QtGui, QtWidgets
from views.main_window import MultiTabMainWindow
import argparse
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
