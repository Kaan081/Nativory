"""Evidence model for experimental NDK provenance tracing (not compatibility)."""
from dataclasses import dataclass
from enum import Enum


class NdkOwnerType(str, Enum):
    PROJECT = "project"
    INSTALLED_DEPENDENCY = "installed_dependency"


class NdkResolutionKind(str, Enum):
    LITERAL = "literal"
    ROOT_INHERITED = "root_inherited"
    UNSUPPORTED_EXPRESSION = "unsupported_expression"


@dataclass(frozen=True)
class NdkDeclaration:
    owner: str
    owner_type: NdkOwnerType
    source: str
    value: str | None
    resolution_kind: NdkResolutionKind
    resolution_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class NdkTraceResult:
    declarations: tuple[NdkDeclaration, ...]
    attention_signals: tuple[str, ...]
