"""
Live Monitoring & Rescoring Loop (Technical Architecture §3.7).

Runs on an interval (default every 5 minutes, configurable via
RESCORE_INTERVAL_MINUTES) and recomputes risk scores only for addresses
touched by new activity since the last cycle — not the whole graph. Uses
APScheduler in-process rather than Celery+broker: same "periodic incremental
rescoring" role from the architecture doc's tech-stack table, with no extra
infra to stand up for a hackathon demo. Swappable for Celery beat later
without touching the callers of risk_service.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.services import audit_service, risk_service, traffic_correlation

logger = logging.getLogger("rescoring")

scheduler = BackgroundScheduler()


def _get_recently_changed_addresses() -> list[str]:
    # Placeholder for "new transactions ingested since the last cycle"
    # (Technical Architecture §3.7). Replace with a query against the
    # ingestion/storage layer for addresses touched since the last run.
    return [f"1MockAddr{i:04d}" for i in range(5)]


def run_rescoring_cycle() -> None:
    # Refresh the traffic-anomaly snapshot first so the fusion step below sees
    # current features. An empty traffic window is a no-op, never an error.
    try:
        traffic_summary = traffic_correlation.refresh()
        audit_service.log_system_event("traffic_refresh", str(traffic_summary))
    except Exception:  # noqa: BLE001 - traffic must not break rescoring
        logger.exception("Traffic refresh failed; continuing rescoring")

    changed = _get_recently_changed_addresses()
    count = risk_service.rescore_neighborhood(changed)
    logger.info("Rescoring cycle complete: %d addresses updated", count)
    audit_service.log_system_event(
        "rescoring_cycle", f"Rescored {count} addresses: {changed}"
    )


def start() -> None:
    scheduler.add_job(
        run_rescoring_cycle,
        trigger="interval",
        minutes=settings.rescore_interval_minutes,
        id="rescoring_cycle",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Rescoring scheduler started (every %d minutes)", settings.rescore_interval_minutes
    )


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
