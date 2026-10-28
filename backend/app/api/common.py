"""Shared HTTP helpers: structured errors, auth, permissions, pagination, rate limiting."""
from __future__ import annotations

import json
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


def ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def error_response(err: ApiError) -> JSONResponse:
    body = {"error": {"code": err.code, "message": err.message}}
    if err.details is not None:
        body["error"]["details"] = err.details
    return JSONResponse(body, status_code=err.status)


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


async def body_as(request: Request, model: type[BaseModel]) -> Any:
    try:
        raw = await request.body()
        data = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise ApiError(400, "invalid_json", "Request body must be valid JSON.")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise ApiError(422, "validation_error", "Request validation failed.", details)


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
    return request.client.host if request.client else "unknown"
