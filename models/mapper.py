# mapper.py
# ---------------------------------------------------------------------------
#  校正表格式 (CSV)
#  ----------------
#  idx,nm
#  550,550.0
#  690,700.0
#  ...
#
#  · idx：馬達計數器讀數（每 1 = 10 pulse）
#  · nm ：對應真實波長
# ---------------------------------------------------------------------------

import csv
import pathlib
import numpy as np
from typing import List

DEFAULT_PATH = pathlib.Path("calibration.csv")
MIN_POINTS = 2

class Mapper:
    """
    · 載入 / 更新校正點 (idx ↔ nm)
    · 內部使用 numpy 內插；點 <2 會 raise ValueError
    """

    def __init__(self, csv_path: pathlib.Path = DEFAULT_PATH) -> None:
        self.csv_path = csv_path
        self.idx_arr: np.ndarray
        self.nm_arr: np.ndarray
        self._load_csv()

    # ------------------------------ file I/O -------------------------------
    def load(self, path: pathlib.Path) -> None:
        """Load calibration data from the given CSV file."""
        self.csv_path = pathlib.Path(path)
        self._load_csv()

    def save(self, path: pathlib.Path | None = None) -> None:
        """Save current calibration data to CSV."""
        if path is not None:
            self.csv_path = pathlib.Path(path)
        self._save_csv()

    # -------------------------------- API ---------------------------------
    def nm_from_idx(self, idx: float) -> float:
        """輸入 idx (float 可)，回傳波長 nm；範圍外 raise ValueError"""
        self._assert_ready()
        if idx < self.idx_arr.min() or idx > self.idx_arr.max():
            raise ValueError("idx 超出校正範圍")
        return float(np.interp(idx, self.idx_arr, self.nm_arr))

    def idx_from_nm(self, nm: float) -> float:
        """輸入波長 nm，回傳 idx；範圍外 raise ValueError"""
        self._assert_ready()
        if nm < self.nm_arr.min() or nm > self.nm_arr.max():
            raise ValueError("nm 超出校正範圍")
        return float(np.interp(nm, self.nm_arr, self.idx_arr))

    def add_point(self, idx: int, nm: float) -> None:
        """新增一點，再排序存檔"""
        idx = int(idx)
        self.idx_arr = np.append(self.idx_arr, idx)
        self.nm_arr = np.append(self.nm_arr, nm)
        sort = self.idx_arr.argsort()
        self.idx_arr = self.idx_arr[sort]
        self.nm_arr = self.nm_arr[sort]
        self._save_csv()

    def point_count(self) -> int:
        return len(self.idx_arr)

    # ------------------------------ internals -----------------------------
    def _load_csv(self) -> None:
        if not self.csv_path.exists():
            # 空表 ── 先放 0 點
            self.idx_arr = np.array([], dtype=float)
            self.nm_arr = np.array([], dtype=float)
            return
        idx_list: List[float] = []
        nm_list: List[float] = []
        with self.csv_path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    idx_list.append(float(row["idx"]))
                    nm_list.append(float(row["nm"]))
                except (KeyError, ValueError):
                    continue
        self.idx_arr = np.array(idx_list, dtype=float)
        self.nm_arr = np.array(nm_list, dtype=float)

    def _save_csv(self) -> None:
        with self.csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["idx", "nm"])
            writer.writerows(zip(self.idx_arr, self.nm_arr))

    def _assert_ready(self) -> None:
        if self.point_count() < MIN_POINTS:
            raise ValueError("校正點不足 (至少需要 2 點)")

    # ------------------------- utility (for CLI) --------------------------
    def __repr__(self) -> str:  # pragma: no cover
        return f"<Mapper points={self.point_count()}>"

    # CLI test
if __name__ == "__main__":
    m = Mapper()
    print("目前校正點：", list(zip(m.idx_arr, m.nm_arr)))
    if m.point_count() >= MIN_POINTS:
        print("  idx 600 → nm =", m.nm_from_idx(600))
        print("  nm  632 → idx =", m.idx_from_nm(632))
    else:
        print("校正點不足，請先 add_point()")
