"""Injected Forge execution boundary for Humanizer qualification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .humanizer import HumanizerBundle
from .humanizer_artifacts import HumanizerAdoptionDecision, assess_humanizer_adoption
from .verification_result import VerificationResultAdapter


class HumanizerForgeError(ValueError):
    """Raised when an injected Forge result cannot be normalized safely."""


ForgeExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class HumanizerForgeOutcome:
    """Normalized Forge result and non-authoritative adoption decision."""

    verification_result: dict[str, Any]
    adoption: HumanizerAdoptionDecision


class HumanizerForgeCoordinator:
    """Send a typed request to an injected Forge executor and gate the result."""

    def __init__(self, executor: ForgeExecutor) -> None:
        self._executor = executor
        self._normalizer = VerificationResultAdapter()

    def verify(self, bundle: HumanizerBundle) -> HumanizerForgeOutcome:
        raw = self._executor(bundle.forge_request)
        if not isinstance(raw, Mapping):
            raise HumanizerForgeError("Forge executor must return an object")
        status = raw.get("status")
        checks = raw.get("checks", ())
        evidence = raw.get("evidence", ())
        if not isinstance(status, str):
            raise HumanizerForgeError("Forge result requires status")
        if not isinstance(checks, list | tuple):
            raise HumanizerForgeError("Forge result checks must be an array")
        if not isinstance(evidence, list | tuple):
            raise HumanizerForgeError("Forge result evidence must be an array")
        try:
            normalized = self._normalizer.normalize(
                request_id=bundle.forge_request["request_id"],
                provider_status=status,
                checks=checks,
                evidence=evidence,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HumanizerForgeError(str(exc)) from exc
        decision = assess_humanizer_adoption(bundle.candidate, normalized)
        return HumanizerForgeOutcome(verification_result=normalized, adoption=decision)
