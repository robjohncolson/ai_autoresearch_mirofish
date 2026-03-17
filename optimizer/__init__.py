"""Optimizer package — failure analysis, patching, quality gates, consensus."""

from .analyzer import FailureAnalyzer
from .patcher import CurriculumPatcher
from .gates import PatchGates
from .consensus import OptimizerConsensus

__all__ = [
    "FailureAnalyzer",
    "CurriculumPatcher",
    "PatchGates",
    "OptimizerConsensus",
]
