"""ToolGateway: the only path from the agent to a tool.
Every call is: allowlist -> JSON-schema arg check -> write guard -> retry loop -> audit log."""
import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_JSON_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}


class ToolError(Exception):
    """Raised by tools. `status` mimics HTTP; None plus timeout=True means the call timed out."""

    def __init__(self, status: int | None, message: str = "", retry_after: float | None = None, timeout: bool = False):
        super().__init__(f"{status or 'timeout'}: {message}")
        self.status, self.retry_after, self.timeout = status, retry_after, timeout


class GuardRejected(Exception):
    """The gateway refused the call before it reached the tool (never retried)."""


def is_retryable(err: Exception) -> bool:
    """Only 429, 5xx and timeouts are retried. 4xx (400/404/409/422) are not.
    LLM errors carry their own classification (RateLimited/Transient retry; Malformed/Fatal don't)."""
    if hasattr(err, "retryable"):
        return bool(err.retryable)
    if isinstance(err, ToolError):
        return err.timeout or err.status == 429 or (err.status is not None and err.status >= 500)
    return isinstance(err, TimeoutError)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    sleep: Callable[[float], None] = time.sleep
    rand: Callable[[], float] = random.random

    def delay(self, attempt: int, err: Exception) -> float:
        """Retry-After wins when present; otherwise exponential backoff with full jitter."""
        retry_after = getattr(err, "retry_after", None)
        if retry_after is not None:
            return min(float(retry_after), self.max_delay)
        return min(self.base_delay * 2 ** (attempt - 1), self.max_delay) * self.rand()


@dataclass
class ToolSpec:
    name: str
    parameters: dict[str, Any]  # JSON schema (object with properties/required)
    handler: Callable[..., Any]
    writes: bool = False        # write tools get an idempotency key and the write guard


SUPPORTED_KEYWORDS = {"type", "properties", "required", "additionalProperties", "enum", "items", "description"}


def idempotency_key(tool: str, args: dict[str, Any]) -> str:
    """Same tool + same args (incl. record id and expected_version) -> same key, across retries and reruns."""
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_args(schema: dict[str, Any], value: Any, path: str = "args") -> None:
    """Small JSON-schema subset: type, properties, required, additionalProperties, enum, items."""
    unsupported = set(schema) - SUPPORTED_KEYWORDS
    if unsupported:  # fail loudly rather than pretend a constraint is enforced
        raise ValueError(f"unsupported JSON-schema keywords in tool spec: {sorted(unsupported)}")
    expected = schema.get("type")
    if expected:
        py = _JSON_TYPES[expected]
        if not isinstance(value, py) or (expected in ("integer", "number") and isinstance(value, bool)):
            raise GuardRejected(f"{path}: expected {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise GuardRejected(f"{path}: {value!r} not in {schema['enum']}")
    if expected == "object":
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                raise GuardRejected(f"{path}: missing {req}")
        for k, v in value.items():
            if k in props:
                validate_args(props[k], v, f"{path}.{k}")
            elif schema.get("additionalProperties", True) is False:
                raise GuardRejected(f"{path}: unexpected key {k}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_args(schema["additionalProperties"], v, f"{path}.{k}")
    if expected == "array" and "items" in schema:
        for i, v in enumerate(value):
            validate_args(schema["items"], v, f"{path}[{i}]")


@dataclass
class ToolGateway:
    tools: dict[str, ToolSpec]
    allowlist: set[str]
    field_whitelist: set[str]
    status_allowlist: set[str]
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    audit_path: Path | None = None
    run_id: str = "run-0"
    clock: Callable[[], str] = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    audit: list[dict[str, Any]] = field(default_factory=list)

    def specs(self) -> list[dict[str, Any]]:
        """Tool specs in function-calling format (used by agent mode, P5.5)."""
        return [{"name": n, "parameters": self.tools[n].parameters} for n in sorted(self.allowlist)]

    def call(self, name: str, args: dict[str, Any]) -> Any:
        try:
            spec = self._check(name, args)
        except GuardRejected as e:
            self._log(name, args, attempt=0, outcome="REJECTED", error=str(e))
            raise
        if spec.writes:
            args = {**args, "idempotency_key": idempotency_key(name, args)}  # deterministic: retries and reruns dedupe
        for attempt in range(1, self.retry.max_attempts + 1):
            try:
                result = spec.handler(**args)
            except Exception as e:
                retry = is_retryable(e) and attempt < self.retry.max_attempts
                self._log(name, args, attempt, "RETRY" if retry else "ERROR", error=str(e))
                if not retry:
                    raise
                self.retry.sleep(self.retry.delay(attempt, e))
                continue
            self._log(name, args, attempt, "OK")
            return result

    def _check(self, name: str, args: dict[str, Any]) -> ToolSpec:
        if name not in self.allowlist or name not in self.tools:
            raise GuardRejected(f"tool {name!r} not allowlisted")
        if "idempotency_key" in args:
            raise GuardRejected("idempotency_key is set by the gateway, not the caller")
        spec = self.tools[name]
        validate_args(spec.parameters, args)
        if spec.writes:
            bad = set(args.get("patch", {})) - self.field_whitelist
            if bad:
                raise GuardRejected(f"fields not whitelisted: {sorted(bad)}")
            status = args.get("status")
            if status is not None and status not in self.status_allowlist:
                raise GuardRejected(f"status {status!r} not allowed")
        return spec

    def _log(self, tool: str, args: dict[str, Any], attempt: int, outcome: str, error: str | None = None) -> None:
        entry = {"run_id": self.run_id, "ts": self.clock(), "tool": tool, "args": args, "attempt": attempt, "outcome": outcome, "error": error}
        self.audit.append(entry)
        if self.audit_path:
            with self.audit_path.open("a") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
