"""Provider-neutral, read-only Herdr observation transport boundary.

This module deliberately stops at mechanics.  It does not expose any Herdr
control operation and the fake provider is the conformance seam used before a
real local socket is considered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import random
import json
import socket

PROTOCOL = 20
SUPPORTED_PROTOCOLS = frozenset({20, 22})
READ_ONLY_METHODS = frozenset({"api.snapshot", "session.snapshot", "pane.get", "events.subscribe", "events.wait"})


class TransportError(RuntimeError):
    """A transport or protocol failure; callers should degrade explicitly."""


@dataclass(frozen=True)
class TransportHealth:
    state: str
    reason: str = ""
    reconnect_attempts: int = 0


@dataclass(frozen=True)
class ReconnectBackoff:
    """Bounded exponential delay calculator; sleeping is owned by the caller."""

    base_seconds: float = 0.25
    max_seconds: float = 30.0
    jitter_ratio: float = 0.2

    def delay(self, attempt: int, *, random_value: float | None = None) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one")
        raw = min(self.max_seconds, self.base_seconds * (2 ** (attempt - 1)))
        sample = random.random() if random_value is None else random_value
        if not 0 <= sample <= 1:
            raise ValueError("random_value must be between zero and one")
        return min(self.max_seconds, raw * (1 - self.jitter_ratio + (2 * self.jitter_ratio * sample)))


def validate_read_only_method(method: str) -> None:
    if method not in READ_ONLY_METHODS:
        raise TransportError(f"Herdr method is outside read-only allowlist: {method}")


def negotiate_protocol(advertised: int) -> int:
    """Select a known protocol; never silently downgrade an unknown one."""
    if advertised not in SUPPORTED_PROTOCOLS:
        raise TransportError(f"unsupported Herdr protocol: {advertised}")
    return advertised


@dataclass(frozen=True)
class HerdrEnvelope:
    method: str
    params: dict = field(default_factory=dict)
    protocol: int = PROTOCOL


class UnixSocketReadOnlyTransport:
    """Verified newline-JSON transport for Herdr's read-only API surface."""

    def __init__(self, socket_path: str, *, timeout_seconds: float = 5.0):
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, params: dict | None = None) -> dict:
        validate_read_only_method(method)
        request = {"id": "core-herdr-observation", "method": method, "params": params or {}}
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(self.timeout_seconds)
            connection.connect(self.socket_path)
            connection.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
            raw = _read_json_line(connection)
        try:
            response = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError("malformed Herdr socket response") from exc
        if "error" in response:
            raise TransportError(response["error"].get("message", "Herdr API error"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise TransportError("Herdr response lacks result object")
        return result

    def subscribe_agent_status(self, pane_id: str | None = None) -> dict:
        subscription = {"type": "pane.agent_status_changed"}
        if pane_id:
            subscription["pane_id"] = pane_id
        return self.request("events.subscribe", {"subscriptions": [subscription]})

    def wait_agent_status(self, pane_id: str, agent_status: str, timeout_ms: int = 1000) -> dict:
        return self.request("events.wait", {"match_event": {"event": "pane_agent_status_changed", "pane_id": pane_id, "agent_status": agent_status}, "timeout_ms": timeout_ms})

    def subscribe_agent_status_stream(self, pane_id: str | None = None) -> "UnixSocketSubscription":
        subscription = {"type": "pane.agent_status_changed"}
        if pane_id:
            subscription["pane_id"] = pane_id
        connection = socket.socket(socket.AF_UNIX)
        connection.settimeout(self.timeout_seconds)
        connection.connect(self.socket_path)
        request = {"id": "core-herdr-observation-stream", "method": "events.subscribe", "params": {"subscriptions": [subscription]}}
        connection.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
        raw = _read_json_line(connection)
        try:
            acknowledgement = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            connection.close()
            raise TransportError("malformed Herdr subscription response") from exc
        if "error" in acknowledgement:
            connection.close()
            raise TransportError(acknowledgement["error"].get("message", "Herdr subscription failed"))
        if acknowledgement.get("result", {}).get("type") != "subscription_started":
            connection.close()
            raise TransportError("Herdr subscription was not started")
        return UnixSocketSubscription(connection)


@dataclass
class UnixSocketSubscription:
    connection: socket.socket

    def poll(self) -> dict:
        try:
            raw = _read_json_line(self.connection)
        except socket.timeout as exc:
            raise TransportError("timed out waiting for Herdr subscription event") from exc
        if not raw:
            raise TransportError("Herdr subscription socket closed")
        try:
            message = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError("malformed Herdr subscription event") from exc
        return message

    def close(self) -> None:
        self.connection.close()


@dataclass
class ReconnectingAgentStatusStream:
    """Read-only stream lifecycle; retry scheduling remains caller-owned."""

    transport: UnixSocketReadOnlyTransport
    pane_id: str | None = None
    backoff: ReconnectBackoff = ReconnectBackoff()
    subscription: UnixSocketSubscription | None = None
    reconnect_attempts: int = 0
    health: TransportHealth = TransportHealth("disconnected", "not started")

    def connect(self) -> None:
        try:
            self.subscription = self.transport.subscribe_agent_status_stream(self.pane_id)
        except (OSError, TransportError) as exc:
            self.health = TransportHealth("degraded", str(exc), self.reconnect_attempts)
            raise
        self.health = TransportHealth("healthy", "subscription started", self.reconnect_attempts)

    def poll(self) -> dict:
        if self.subscription is None:
            self.connect()
        try:
            return self.subscription.poll()
        except TransportError as exc:
            self.health = TransportHealth("degraded", str(exc), self.reconnect_attempts)
            self.subscription.close()
            self.subscription = None
            raise

    def reconnect(self) -> float:
        if self.subscription is not None:
            self.subscription.close()
            self.subscription = None
        self.reconnect_attempts += 1
        delay = self.backoff.delay(self.reconnect_attempts, random_value=0.5)
        self.connect()
        return delay


def _read_json_line(connection: socket.socket, *, max_bytes: int = 1024 * 1024) -> bytes:
    """Read exactly one bounded newline-delimited API message."""
    chunks = bytearray()
    while len(chunks) < max_bytes:
        chunk = connection.recv(min(65536, max_bytes - len(chunks)))
        if not chunk:
            break
        chunks.extend(chunk)
        if b"\n" in chunk:
            line, _, _ = bytes(chunks).partition(b"\n")
            return line
    if not chunks:
        raise TransportError("Herdr socket closed before response")
    if b"\n" not in chunks:
        raise TransportError("Herdr response exceeded framing limit or lacked newline")
    return bytes(chunks).split(b"\n", 1)[0]


class FakeHerdrProvider:
    """Deterministic snapshots/subscription source for adapter conformance."""

    def __init__(self, *, protocol: int = PROTOCOL, snapshots: dict | None = None):
        self.protocol = protocol
        self.snapshots = snapshots or {}
        self.subscribers: list[Callable[[dict], None]] = []
        self.connected = True
        self.subscription_count = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        validate_read_only_method(method)
        if not self.connected:
            raise TransportError("fake Herdr provider is disconnected")
        negotiate_protocol(self.protocol)
        params = params or {}
        if method == "api.snapshot":
            return {"protocol": self.protocol, "panes": list(self.snapshots.values())}
        if method == "pane.get":
            pane = self.snapshots.get(params.get("pane_id"))
            if pane is None:
                raise TransportError("pane not found")
            return pane
        if method == "events.subscribe":
            return {"subscribed": True, "topic": params.get("topic")}
        return {"event": None}

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self.request("events.subscribe", {"topic": "pane.agent_status_changed"})
        self.subscription_count += 1
        self.subscribers.append(callback)

    def validate_message(self, message: dict) -> dict:
        """Validate the minimal event envelope before handing it to a consumer."""
        if not isinstance(message, dict):
            raise TransportError("malformed or incompatible Herdr event envelope")
        negotiate_protocol(int(message.get("protocol", self.protocol)))
        if message.get("method") not in {"pane.agent_status_changed", "pane_agent_status_changed"}:
            raise TransportError("unexpected Herdr event method")
        if not isinstance(message.get("params"), dict):
            raise TransportError("Herdr event params must be an object")
        return message

    def emit(self, message: dict) -> None:
        if not self.connected:
            raise TransportError("fake Herdr provider is disconnected")
        message = self.validate_message(message)
        for callback in tuple(self.subscribers):
            callback(message)

    def disconnect(self) -> None:
        self.connected = False
        # A socket loss invalidates registrations; reconnect must resubscribe.
        self.subscribers.clear()

    def reconnect(self) -> None:
        self.connected = True


@dataclass
class ReadOnlySubscription:
    """Reconnect helper; callers provide the callback again after a loss."""

    provider: FakeHerdrProvider
    callback: Callable[[dict], None]
    reconnect_attempts: int = 0
    health: TransportHealth = TransportHealth("healthy")

    def reconnect(self) -> None:
        self.reconnect_attempts += 1
        try:
            self.provider.reconnect()
            self.provider.subscribe(self.callback)
        except TransportError as exc:
            self.health = TransportHealth("degraded", str(exc), self.reconnect_attempts)
            raise
        self.health = TransportHealth("healthy", "resubscribed", self.reconnect_attempts)

    def close(self) -> None:
        def same_callback(item) -> bool:
            return item == self.callback or (
                getattr(item, "__self__", None) is getattr(self.callback, "__self__", None)
                and getattr(item, "__func__", None) is getattr(self.callback, "__func__", None)
            )
        self.provider.subscribers = [item for item in self.provider.subscribers if not same_callback(item)]
        self.health = TransportHealth("disabled", "subscription closed", self.reconnect_attempts)


def reconcile_sequence(previous: int | None, current: int | None, *, generation_changed: bool = False) -> dict:
    """Classify continuity without assuming counters survive server replacement."""
    if current is None or previous is None or generation_changed:
        return {"state": "reconcile", "gap": False, "reason": "unknown_or_new_generation"}
    if current == previous + 1:
        return {"state": "continuous", "gap": False, "reason": "next_sequence"}
    if current > previous + 1:
        return {"state": "reconcile", "gap": True, "reason": "sequence_gap"}
    return {"state": "replay_or_reset", "gap": False, "reason": "non_monotonic_sequence"}
