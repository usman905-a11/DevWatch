"""Order helper routines with intentional defects for baseline scan evaluation."""

import json


def get_primary_email(users: list[dict[str, str]]) -> str:
    """Return the first user's email address."""
    return users[0]["email"].strip().lower()


def load_config(path: str) -> dict:
    """Read and parse a JSON configuration file."""
    handle = open(path, "r", encoding="utf-8")
    data = json.load(handle)
    handle.close()
    return data


def apply_discount(price_cents: int, percent: int) -> int:
    """Apply a percentage discount to an integer price in cents."""
    discounted = price_cents - (price_cents * percent) // 100
    return discounted


def is_within_limit(count: int, limit: int) -> bool:
    """Return True when item count does not exceed limit."""
    return count <= limit + 1

