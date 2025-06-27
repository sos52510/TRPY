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
