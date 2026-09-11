import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import address, ai, alerts, audit, auth, graph, traffic
from app.capture.manager import capture_manager
from app.core.config import settings
from app.core.security import decode_access_token
from app.scheduler import rescoring
from app.services import audit_service

logger = logging.getLogger("sentrix")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        capture_manager.start()
    except Exception:  # noqa: BLE001 - capture is best-effort, never blocks startup
        logger.exception("traffic capture failed to start; continuing without it")
    rescoring.start()
    yield
    rescoring.shutdown()
    try:
        capture_manager.stop()
    except Exception:  # noqa: BLE001
        logger.exception("traffic capture failed to stop cleanly")


app = FastAPI(
    title="SentriX Backend API",
    description="Backend API & Live Loop for SIH26146 — AI-Powered Monitoring "
    "& Analysis of Bitcoin Transaction Traffic (Team ZENITH).",
    version="0.1.0",
    lifespan=lifespan,
)


# Browser access for the dashboard. Registered before the audit middleware so
# CORS headers are attached outermost and therefore survive on every response,
# including the 401s the auth dependency raises.
#
# allow_methods/allow_headers are restricted rather than wildcarded: the API
# only exposes GET and POST (10 and 3 routes respectively), and the browser
# only ever needs to send Authorization (the JWT) plus Content-Type (the
# form-encoded login body). allow_credentials stays off because the token
# travels in a header, not a cookie -- and a wildcard origin with credentials
# enabled is rejected by browsers anyway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _identify_caller(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return "anonymous"
    payload = decode_access_token(auth_header.removeprefix("Bearer "))
    if not payload:
        return "anonymous"
    return payload.get("sub", "anonymous")


@app.middleware("http")
async def audit_logging_middleware(request: Request, call_next):
    response = await call_next(request)
    audit_service.log_request(
        user=_identify_caller(request),
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
    )
    return response


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(address.router)
app.include_router(alerts.router)
app.include_router(graph.router)
app.include_router(traffic.router)
app.include_router(ai.router)
app.include_router(audit.router)
