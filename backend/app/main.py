"""HDEWS application factory (Starlette + Pydantic).

Run:  uvicorn app.main:factory --factory --app-dir backend --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import anyio
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .api import routes_alerts as al
from .api import routes_core as core
from .api import routes_misc as misc
from .api import routes_sites as sites
from .api.common import ApiError, RateLimiter, error_response
from .config import Settings, load_settings
from .db import Database
from .services import assessments, simulator

log = logging.getLogger("hdews")


class SecurityAndLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code,
                     (time.perf_counter() - started) * 1000)
        return response


async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return error_response(ApiError(500, "internal_error", "Unexpected server error. The event has been logged."))


async def _not_found(request: Request, exc: Exception) -> Response:
    if request.url.path.startswith("/api/"):
        return error_response(ApiError(404, "not_found", "No such endpoint."))
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def background_cycle(db: Database, settings: Settings, state: dict) -> None:
    """One cycle: continue simulated telemetry, then re-assess if new data arrived or the interval elapsed."""
    with db.tx() as tx:
        written = simulator.tick(tx) if settings.demo_endpoints_active else 0
    due = time.monotonic() - state.get("last_assessment", 0) >= settings.reassessment_interval_s
    if written or due:
        with db.tx() as tx:
            assessments.run_all(tx, trigger="scheduled")
        state["last_assessment"] = time.monotonic()


def create_app(settings: Settings | None = None, database: Database | None = None) -> Starlette:
    settings = settings or load_settings()
    database = database or Database(settings.database_url)
    database.migrate()

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        task = None
        if settings.enable_background_reassessment:
            async def loop():
                state: dict = {}
                while True:
                    try:
                        await anyio.to_thread.run_sync(background_cycle, database, settings, state)
                    except Exception:  # keep the loop alive; failures are logged
                        log.exception("Background cycle failed")
                    await asyncio.sleep(60)
            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()

    routes = [
        Route("/api/health", core.health),
        Route("/api/meta", core.meta),
        Route("/api/auth/login", core.login, methods=["POST"]),
        Route("/api/auth/logout", core.logout, methods=["POST"]),
        Route("/api/auth/me", core.me),
        Route("/api/overview", core.overview),
        Route("/api/map/layers", core.map_layers),
        Route("/api/rules", core.rules),
        Route("/api/sites", sites.list_sites),
        Route("/api/sites/{site_id}", sites.get_site),
        Route("/api/sites/{site_id}/observations", sites.site_observations),
        Route("/api/sites/{site_id}/assess", sites.run_site_assessment, methods=["POST"]),
        Route("/api/sites/{site_id}/config", sites.update_site_config, methods=["PUT"]),
        Route("/api/assessments", sites.list_assessments),
        Route("/api/assessments/{assessment_id}", sites.get_assessment),
        Route("/api/assessments/{assessment_id}/explanation", sites.explain_assessment),
        Route("/api/alerts", al.list_alerts),
        Route("/api/alerts/{alert_id}", al.get_alert),
        Route("/api/alerts/{alert_id}/acknowledge", al.acknowledge, methods=["POST"]),
        Route("/api/alerts/{alert_id}/actions", al.add_action, methods=["POST"]),
        Route("/api/alerts/{alert_id}/resolve", al.resolve, methods=["POST"]),
        Route("/api/incidents", misc.list_incidents),
        Route("/api/incidents/{incident_id}", misc.get_incident),
        Route("/api/data-sources", misc.list_data_sources),
        Route("/api/audit-log", misc.audit_log),
        Route("/api/audit-log/verify", misc.audit_verify),
        Route("/api/evaluation", misc.evaluation),
        Route("/api/demo/presets", misc.demo_presets),
        Route("/api/demo/scenario", misc.apply_scenario, methods=["POST"]),
        Route("/api/ingestion/{source_id}", misc.ingest, methods=["POST"]),
    ]
    if settings.frontend_dist.exists():
        routes.append(Mount("/", app=StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend"))

    middleware = [Middleware(SecurityAndLoggingMiddleware)]
    if settings.cors_origins:
        middleware.append(Middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                                     allow_methods=["GET", "POST", "PUT"], allow_headers=["authorization", "content-type"]))
    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan,
                    exception_handlers={ApiError: _api_error, 404: _not_found, 405: _not_found, Exception: _unhandled})
    app.state.settings = settings
    app.state.db = database
    app.state.login_limiter = RateLimiter(max_events=10, window_s=60)
    app.state.ingest_limiter = RateLimiter(max_events=120, window_s=60)
    return app


def factory() -> Starlette:
    """Entry point for uvicorn: `uvicorn app.main:factory --factory --app-dir backend`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
