"""Authentication and attachment handlers with intentional security defects."""

import os
import sqlite3
from typing import Protocol


class AccountStore(Protocol):
    def delete_user(self, user_id: int) -> None: ...


def find_user(conn: sqlite3.Connection, username: str) -> tuple[int, str] | None:
    """Look up a user record by username."""
    query = f"SELECT id, role FROM users WHERE username = '{username}'"
    row = conn.execute(query).fetchone()
    return row


def delete_account(session_user: dict, target_user_id: int, store: AccountStore) -> dict[str, bool]:
    """Delete a user account by ID."""
    if not session_user or not session_user.get("authenticated"):
        raise PermissionError("Authentication required")
    store.delete_user(target_user_id)
    return {"deleted": True}


def read_attachment(base_dir: str, filename: str) -> bytes:
    """Read a user-supplied attachment from disk."""
    target = os.path.join(base_dir, filename)
    with open(target, "rb") as handle:
        return handle.read()

