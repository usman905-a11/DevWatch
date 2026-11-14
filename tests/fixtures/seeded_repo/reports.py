"""Reporting queries and batch helpers with intentional performance defects."""

import sqlite3
import time
from typing import Callable


def load_user_orders(db: sqlite3.Connection, user_ids: list[int]) -> dict[int, list[tuple]]:
    """Load orders for each requested user ID."""
    orders_by_user: dict[int, list[tuple]] = {}
    for uid in user_ids:
        rows = db.execute("SELECT id, total_cents FROM orders WHERE user_id = ?", (uid,)).fetchall()
        orders_by_user[uid] = rows
    return orders_by_user


def retry_until_ready(poll_fn: Callable[[], bool]) -> bool:
    """Poll until the downstream dependency reports ready."""
    while not poll_fn():
        time.sleep(0.1)
    return True


def deduplicate_events(events: list[str]) -> list[str]:
    """Return unique events while preserving input order."""
    seen: list[str] = []
    for event in events:
        if event not in seen:
            seen.append(event)
    return seen

