"""Evidence fusion: typed multi-hop path search over stored facts (see ADR-0006)."""

from .paths import (
    EvidenceGraph,
    FusionPath,
    FusionResult,
    build_evidence_graph,
    evidence_fusion,
    render_path,
    search_paths,
)
from .plan import AnswerType, Cue, QuestionPlan, detect_answer_type, plan_question

__all__ = [
    "AnswerType",
    "Cue",
    "EvidenceGraph",
    "FusionPath",
    "FusionResult",
    "QuestionPlan",
    "build_evidence_graph",
    "detect_answer_type",
    "evidence_fusion",
    "plan_question",
    "render_path",
    "search_paths",
]
