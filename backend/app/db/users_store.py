"""
Demo identity store for the hackathon prototype.

Roles: "admin", "investigator", "analyst" (see Project Scope §9 — role-based,
multi-tenant access so multiple agencies can share one backend).
Swap this module for a real user table (e.g. Postgres) post-hackathon; every
other module only depends on get_user() / USERS, so the swap is contained here.
"""
from app.core.security import get_password_hash

USERS = {
    "admin": {
        "username": "admin",
        "hashed_password": get_password_hash("admin123"),
        "role": "admin",
        "agency": "NTRO",
    },
    "investigator1": {
        "username": "investigator1",
        "hashed_password": get_password_hash("investigate123"),
        "role": "investigator",
        "agency": "NTRO",
    },
    "analyst1": {
        "username": "analyst1",
        "hashed_password": get_password_hash("analyst123"),
        "role": "analyst",
        "agency": "FIU-IND",
    },
}


def get_user(username: str) -> dict | None:
    return USERS.get(username)
