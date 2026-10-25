"""Profile-gated transformation rules for the Core Humanizer boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


HumanizerRule = Callable[[str], str]


class RuleBasedHumanizerProvider:
    """Apply only rules explicitly allowlisted by a project profile.

    The rules are injected by the owning implementation. Core does not infer
    style from arbitrary source or enable transformations implicitly.
    """

    def __init__(
        self,
        *,
        profiles: Mapping[str, Sequence[str]],
        rules: Mapping[str, HumanizerRule],
    ) -> None:
        self._profiles = {name: tuple(rule_ids) for name, rule_ids in profiles.items()}
        self._rules = dict(rules)
        unknown = {
            rule_id
            for rule_ids in self._profiles.values()
            for rule_id in rule_ids
            if rule_id not in self._rules
        }
        if unknown:
            raise ValueError(f"profiles reference unknown Humanizer rules: {sorted(unknown)}")

    def __call__(self, request: Mapping[str, Any]) -> dict[str, str]:
        target = request.get("target")
        source = request.get("source")
        profile = request.get("profile")
        request_id = request.get("request_id", "unknown")
        if not isinstance(target, str) or not isinstance(source, str):
            raise ValueError("Humanizer request requires target and source")
        if profile is not None and not isinstance(profile, str):
            raise ValueError("Humanizer profile must be a string or null")

        content = source
        applied: list[str] = []
        for rule_id in self._profiles.get(profile or "", ()):
            content = self._rules[rule_id](content)
            if not isinstance(content, str):
                raise ValueError(f"Humanizer rule {rule_id!r} returned non-string content")
            applied.append(rule_id)
        return {
            "candidate_content": content,
            "candidate_path": target,
            "transformation_manifest_ref": f"artifacts/humanizer/{request_id}/manifest.json",
            "rules_applied": applied,
        }
