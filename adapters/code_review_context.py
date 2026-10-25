"""Build a bounded, provider-neutral package for one code review attempt."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


class ReviewContextError(ValueError):
    """Raised when the review package is incomplete or unbounded."""


@dataclass(frozen=True)
class ReviewPackage:
    """The only context a review provider needs for one implementation attempt."""

    attempt_ref: str
    specification: str
    diff: str
    changed_files: tuple[str, ...]
    tests: tuple[Mapping[str, Any], ...]
    architecture_refs: tuple[str, ...]
    classification: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "code-review-package.v1",
            **asdict(self),
            "changed_files": list(self.changed_files),
            "tests": [dict(item) for item in self.tests],
            "architecture_refs": list(self.architecture_refs),
            "classification": dict(self.classification),
        }


def build_review_package(
    *,
    attempt_ref: str,
    specification: str,
    diff: str,
    changed_files: Sequence[str],
    tests: Sequence[Mapping[str, Any]] = (),
    architecture_refs: Sequence[str] = (),
    classification: Mapping[str, Any] | None = None,
) -> ReviewPackage:
    """Build review context from caller-owned evidence without reading or mutating files."""

    if not attempt_ref.strip():
        raise ReviewContextError("attempt_ref is required")
    if not specification.strip():
        raise ReviewContextError("specification is required")
    if not diff.strip():
        raise ReviewContextError("diff is required")
    files = tuple(str(path).strip() for path in changed_files if str(path).strip())
    if not files:
        raise ReviewContextError("at least one changed file is required")
    if any(not isinstance(item, Mapping) for item in tests):
        raise ReviewContextError("tests must contain mapping records")
    refs = tuple(str(ref).strip() for ref in architecture_refs if str(ref).strip())
    if classification is None:
        classification = {}
    if not isinstance(classification, Mapping):
        raise ReviewContextError("classification must be a mapping")
    return ReviewPackage(
        attempt_ref=attempt_ref.strip(),
        specification=specification,
        diff=diff,
        changed_files=files,
        tests=tuple(dict(item) for item in tests),
        architecture_refs=refs,
        classification=dict(classification),
    )
