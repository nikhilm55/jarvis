"""Wake word: the ONNX detector (openWakeWord pipeline) and the first-word gate."""

from jarvis.wake.detector import Backends, WakeDetector
from jarvis.wake.gate import GateResult, gate

__all__ = ["Backends", "GateResult", "WakeDetector", "gate"]
