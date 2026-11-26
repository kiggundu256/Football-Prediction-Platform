"""QtCore fallback used only when the cloud runner has no PySide6 runtime."""
import threading

class _BoundSignal:
    def __init__(self): self._slots=[]
    def connect(self,slot): self._slots.append(slot)
    def emit(self,*args,**kwargs):
        for slot in tuple(self._slots): slot(*args,**kwargs)

class Signal:
    def __init__(self,*_types): self._name=None
    def __set_name__(self,owner,name): self._name=name
    def __get__(self,instance,owner):
        if instance is None: return self
        signals=instance.__dict__.setdefault("_cloud_fallback_signals",{})
        return signals.setdefault(self._name,_BoundSignal())

class QThread(threading.Thread):
    def __init__(self,*args,**kwargs): super().__init__()
