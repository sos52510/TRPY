from abc import ABC, abstractmethod
import pyvisa
import time
from types import MappingProxyType               # 只需一次即可
import math

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
    _REF_MODE   = {"INT_F":0,"INT_2F":1,"EXT_F":2,"EXT_2F":3}
    _SENS       = {"100 nV":-2,"300 nV":-1,"1 µV":0,"3 µV":1,"10 µV":2,"30 µV":3,
                   "100 µV":4,"300 µV":5,"1 mV":6,"3 mV":7,"10 mV":8,"30 mV":9,
                   "100 mV":10,"300 mV":11,"1 V":12}
    _TIME_CONST = {"0.1 ms":0,"3 ms":1,"10 ms":2,"30 ms":3,"100 ms":4,
                   "300 ms":5,"1 s":6,"3 s":7,"10 s":8,"30 s":9}
    _FMO = {"THRU":0,"HPF":1,"LPF":2,"NORMAL Q1":30,"NORMAL Q5":31,"NORMAL Q30":32,
            "LPF Q1":33,"LPF Q5":34,"LPF Q30":35,"LPF Q1B":36,"LPF Q5B":37,"LPF Q30B":38}
    _OFQ_RANGE = {
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
        if g('ref_mode'):cmd.append(f"BRM{self._REF_MODE[g('ref_mode')]}")
        if g('sensitivity'):cmd.append(f"BSS{self._SENS[g('sensitivity')]}")
        if g('time_const'):cmd.append(f"BTC{self._TIME_CONST[g('time_const')]}")
        if g('filter_mode'):cmd.append(f"FMO{self._FMO[g('filter_mode')]}")
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
        }
        cmd = []
        g = kw.get
        if g('ref_mode')      : cmd.append(f"BRM{maps['ref_mode'][g('ref_mode')]}")
        if g('sensitivity')   : cmd.append(f"BSS{maps['sensitivity'][g('sensitivity')]}")
        if g('time_const')    : cmd.append(f"BTC{maps['time_const'][g('time_const')]}")
        if g('filter_mode')   : cmd.append(f"FMO{maps['filter_mode'][g('filter_mode')]}")
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
