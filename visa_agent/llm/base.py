"""Provider-neutral LLM interface and the error taxonomy every adapter must map to."""
from typing import Any, Protocol


class LLMError(Exception):
    """Base class. `retryable` tells the RetryPolicy whether another attempt can help."""
    retryable = False

    def __init__(self, message: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimited(LLMError):   # HTTP 429
    retryable = True


class Transient(LLMError):     # 5xx, timeout, connection reset
    retryable = True


class Malformed(LLMError):     # output is not valid JSON / fails the schema; handled by one re-ask, not retry
    retryable = False


class Fatal(LLMError):         # auth, bad request, unknown model
    retryable = False


class LLMClient(Protocol):
    name: str

    def extract(self, doc_id: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON object conforming to `schema`, or raise an LLMError subclass."""
        ...


def map_error(e: Exception) -> LLMError:
    """Duck-typed SDK error -> taxonomy (works for google-genai and groq; no SDK import needed)."""
    if isinstance(e, LLMError):
        return e
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    code = code if isinstance(code, int) else None
    hdrs = getattr(getattr(e, "response", None), "headers", None) or {}
    try:
        ra = float(hdrs.get("retry-after"))
    except (TypeError, ValueError):
        ra = None
    kind = type(e).__name__
    if code == 429 or "RateLimit" in kind:
        return RateLimited(str(e), retry_after=ra)
    if (code is not None and code >= 500) or code == 408 or "Timeout" in kind or "Connection" in kind:
        return Transient(str(e), retry_after=ra)
    return Fatal(f"{kind}: {e}")
