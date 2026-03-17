"""Synthetic student simulation engine for AP Statistics autoresearch.

Exports the main classes and helpers:

- ``KCState``, ``StudentMemory``, ``recall_probability`` -- KC state machine
- ``StudentPersona``, ``SyntheticStudent`` -- individual student model
- ``StudentCohort`` -- parallel cohort evaluation manager
- ``build_student_system_prompt``, ``build_item_prompt`` -- prompt templates
"""

from .memory import KCState, StudentMemory, recall_probability
from .student import StudentPersona, SyntheticStudent
from .cohort import StudentCohort
from .prompts import build_student_system_prompt, build_item_prompt

__all__ = [
    "KCState",
    "StudentMemory",
    "recall_probability",
    "StudentPersona",
    "SyntheticStudent",
    "StudentCohort",
    "build_student_system_prompt",
    "build_item_prompt",
]
