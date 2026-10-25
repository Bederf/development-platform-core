from __future__ import annotations

from types import SimpleNamespace

from adapters.radix.spec_kit_discovery import discover_spec_kit


def test_missing_spec_kit_is_explicitly_unavailable() -> None:
    result = discover_spec_kit(which=lambda _name: None)
    assert result["status"] == "unavailable"
    assert result["executable"] is None


def test_spec_kit_version_is_discovered_read_only() -> None:
    calls: list[tuple[list[str], dict]] = []

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="specify-cli 0.1.0\n", stderr="")

    result = discover_spec_kit(which=lambda _name: "/usr/local/bin/specify", runner=runner)
    assert result["status"] == "available"
    assert result["version"] == "specify-cli 0.1.0"
    assert calls[0][0] == ["/usr/local/bin/specify", "--version"]
    assert calls[0][1]["check"] is False


def test_failed_version_probe_remains_unavailable() -> None:
    result = discover_spec_kit(
        which=lambda _name: "/usr/local/bin/specify",
        runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="probe failed"),
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "specify version probe returned a non-zero status"
