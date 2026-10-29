"""Shared HTTP helpers: structured errors, auth, permissions, pagination, rate limiting."""
from __future__ import annotations

import json
import math
import threading
import time
from functools import wraps
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .. import security


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        self.status, self.code, self.message, self.details = status, code, message, details


MAX_BODY_BYTES = 1_000_000  # largest legitimate request (500 ingestion readings) is ~70 kB


def _finite(value: Any) -> Any:
    """Replace NaN/Infinity (not valid JSON) with null so one bad stored value cannot crash a view (HDEWS-001)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(_finite(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def ok(data: Any, status: int = 200) -> JSONResponse:
    return SafeJSONResponse(data, status_code=status)


def error_response(err: ApiError) -> JSONResponse:
    body = {"error": {"code": err.code, "message": err.message}}
    if err.details is not None:
        body["error"]["details"] = err.details
    return SafeJSONResponse(body, status_code=err.status)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a valid number")


def db(request: Request):
    return request.app.state.db


def settings(request: Request):
    return request.app.state.settings


def current_user(request: Request) -> dict | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    with db(request).tx() as tx:
        return security.user_for_token(tx, token)


Handler = Callable[..., Awaitable[Any]]


def require(permission: str) -> Callable[[Handler], Handler]:
    """Decorator: authenticate the request and check a permission. Passes `user` to the handler."""
    def decorator(fn: Handler) -> Handler:
        @wraps(fn)
        async def wrapper(request: Request):
            user = current_user(request)
            if not user:
                raise ApiError(401, "unauthenticated", "Sign in to continue.")
            if not security.can(user, permission):
                raise ApiError(403, "forbidden",
                               f"Your role ({user['role']}) does not have the '{permission}' permission.",
                               {"required_roles": sorted(security.PERMISSIONS[permission])})
            return await fn(request, user)
        return wrapper
    return decorator


async def read_body(request: Request, limit: int = MAX_BODY_BYTES) -> bytes:
    """Read the body without buffering more than `limit` bytes (HDEWS-004)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "payload_too_large", f"Request body exceeds {limit} bytes.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(413, "payload_too_large", f"Request body exceeds {limit} bytes.")
        chunks.append(chunk)
    return b"".join(chunks)


async def body_as(request: Request, model: type[BaseModel]) -> Any:
    raw = await read_body(request)
    try:
        # NaN / Infinity are not JSON; Python's parser would otherwise accept them (HDEWS-001).
        data = json.loads(raw or b"{}", parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError(400, "invalid_json", "Request body must be valid JSON.")
    except ValueError as exc:
        raise ApiError(400, "invalid_json", f"Request body must be valid JSON: {exc}.")
    if not isinstance(data, dict):
        raise ApiError(422, "validation_error", "Request body must be a JSON object.")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ApiError(422, "validation_error", "Request validation failed.", validation_details(exc))


def validation_details(exc: ValidationError) -> list[dict]:
    # Only field paths and messages: never echo submitted values back (they may contain secrets).
    return [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]


def paging(request: Request, default: int = 50, maximum: int = 200) -> tuple[int, int]:
    try:
        limit = int(request.query_params.get("limit", default))
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        raise ApiError(422, "validation_error", "limit and offset must be integers.")
    if limit < 1 or limit > maximum or offset < 0:
        raise ApiError(422, "validation_error", f"limit must be 1–{maximum}; offset must be ≥ 0.")
    return limit, offset


def page(items: list, total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(items) < total}


class RateLimiter:
    """Small in-memory sliding-window limiter (per process). Adequate for a single-node prototype."""

    def __init__(self, max_events: int, window_s: float):
        self.max_events, self.window_s = max_events, window_s
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < self.window_s]
            if len(events) >= self.max_events:
                self._events[key] = events
                raise ApiError(429, "rate_limited", "Too many requests; slow down and retry shortly.")
            events.append(now)
            self._events[key] = events


def client_key(request: Request) -> str:
    """Client identity for rate limiting (HDEWS-041).

    Behind a platform proxy the TCP peer is the proxy, so all users would share one login bucket (one person
    could lock everyone out, and the limit would be meaningless per client). CLIENT_IP_SOURCE selects the
    X-Forwarded-For entry that the proxy guarantees; only enable it when the app is reachable solely
    through that proxy, otherwise clients could spoof the header.
    """
    peer = request.client.host if request.client else "unknown"
    source = settings(request).client_ip_source
    if source == "peer":
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if not hops:
        return peer
    return (hops[0] if source == "x-forwarded-for-first" else hops[-1])[:64]
