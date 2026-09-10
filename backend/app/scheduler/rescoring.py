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


# How many of the top-ranked addresses to refresh per cycle. The dashboard
# displays a top slice (25 rows, 12 alerts); refreshing the top 100 covers that
# with enough headroom that an address near the cutoff does not churn out of the
# refreshed set as the live traffic term shifts the fused ranking between
# cycles. Cheap to widen: `top_ranked_addresses` reads through the score cache,
# so already-cached addresses cost a dict lookup rather than a re-fuse.
RESCORE_POOL = 100

# Retained so the demo addresses keep a fresh timestamp too. They are not in the
# exported graph, so they would otherwise fall out of the rescoring set entirely
# now that the pool is real.
_DEMO_ADDRESSES = [f"1MockAddr{i:04d}" for i in range(5)]


def _get_recently_changed_addresses() -> list[str]:
    """Addresses to rescore this cycle.

    Still a stand-in for "new transactions ingested since the last cycle"
    (Technical Architecture §3.7) -- there is no ingestion layer to query yet.
    But it now returns the top-ranked real addresses rather than a fixed list of
    synthetic strings.

    That distinction is the whole point of the loop. `risk_service`'s cache is
    write-once on read (`get_address_risk` only computes on a miss), so an
    address is frozen at its first-seen score until something explicitly
    overwrites it. `rescore_neighborhood` is that something, and it can only
    refresh addresses named here. Previously that was five `1MockAddr` strings
    absent from the exported graph, so every address the dashboard actually
    shows kept its first-computed traffic component indefinitely -- for hours,
    while live capture updated every cycle and was applied to nothing.
    """
    return risk_service.top_ranked_addresses(limit=RESCORE_POOL) + _DEMO_ADDRESSES


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
    # Log a sample rather than all ~55 ids: enough to verify the loop is hitting
    # real ranked addresses, without a 1 KB audit line every five minutes.
    sample = ", ".join(changed[:5])
    audit_service.log_system_event(
        "rescoring_cycle", f"Rescored {count} addresses (top: {sample})"
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
