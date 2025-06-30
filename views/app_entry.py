import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def ensure_dependencies():
    """Install required packages on the fly if missing."""
    import importlib.util
    import subprocess

    required = [
        ("PyQt5", "PyQt5"),
        ("pyvisa", "pyvisa"),
        ("pyvisa_py", "pyvisa-py"),
        ("serial", "pyserial"),
        ("matplotlib", "matplotlib"),
        ("numpy", "numpy"),
    ]
    missing = [pip for mod, pip in required if importlib.util.find_spec(mod) is None]
    if missing:
        print(f"🛠 Installing missing packages: {missing}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("✅ Dependencies installed. Please rerun the program.")
        except Exception as exc:  # noqa: broad-except
            print("❌ Failed to install packages:", exc)
        sys.exit(0)

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
