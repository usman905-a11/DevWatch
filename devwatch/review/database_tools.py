"""Explicit owner-granted, read-only SQLite metadata and query-plan inspection."""
import asyncio
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import time

from pydantic import ConfigDict, Field

from devwatch.review.contracts import AGENT_CONTRACTS, ContractModel
from devwatch.review.tool_runtime import _drain
from devwatch.review.tool_errors import ToolFailure


class DatabasePolicy(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    database_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    path: Path
    owners: frozenset[str] = Field(min_length=1, max_length=100)


class DatabaseTools:
    def __init__(self, repository, job, *, policies=()):
        self.repo, self.job = repository, job
        self.policies = {policy.database_id: policy for policy in policies}
        if len(self.policies) != len(policies) or len(policies) > 20:
            raise ValueError("Database policy registry must be bounded and unique")

    def _inspect(self, policy, arguments, tool):
        path = policy.path.resolve(strict=True)
        if not path.is_file():
            raise ValueError("Database must be a regular local file")
        deadline = time.monotonic() + 2
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            def authorize(code, first, second, database, trigger):
                allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}
                if code in allowed or (code == sqlite3.SQLITE_PRAGMA and first == "table_info"):
                    return sqlite3.SQLITE_OK
                if code == sqlite3.SQLITE_FUNCTION and second.lower() in {"count", "sum", "min", "max", "avg", "length", "lower", "upper", "coalesce", "ifnull", "abs", "round", "json_extract", "like"}:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            db.set_authorizer(authorize)
            db.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
            if tool == "query_analyze":
                query = arguments.get("query")
                parameters = arguments.get("parameters", [])
                if (not isinstance(query, str) or len(query.encode()) > 8192 or not re.match(r"(?is)^\s*select\b", query)
                        or not isinstance(parameters, list) or len(parameters) > 30
                        or any(not isinstance(value, (str, int, float, type(None))) for value in parameters)):
                    raise PermissionError("Only bounded SELECT query plans are permitted")
                plan = db.execute("EXPLAIN QUERY PLAN " + query, parameters).fetchmany(100)
                return {"database_id": policy.database_id, "query_plan": plan,
                        "limitations": ["Query plans describe the current read-only database, not runtime timings"]}
            tables = []
            for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 50"):
                escaped = name.replace('"', '""')
                columns = db.execute(f'PRAGMA table_info("{escaped}")').fetchmany(100)
                tables.append({"name": name, "columns": [{"name": column[1], "type": column[2]} for column in columns]})
            return {"database_id": policy.database_id, "tables": tables,
                    "limitations": ["Schema inspection is bounded to fifty tables and one hundred columns per table; no row values returned"]}

    async def execute(self, task, action):
        AGENT_CONTRACTS[task.agent_id].validate_action(action)
        allowed = {"database_id"} if action.tool == "db_analyze" else {"database_id", "query", "parameters"}
        if action.tool not in {"db_analyze", "query_analyze"} or set(action.arguments) - allowed:
            raise PermissionError("Invalid database tool request")
        policy = self.policies.get(action.arguments.get("database_id"))
        if policy is None or self.job.owner not in policy.owners:
            raise PermissionError("Database is not granted to this owner")
        operation = asyncio.create_task(asyncio.to_thread(self._inspect, policy, action.arguments, action.tool))
        try:
            data = await asyncio.shield(operation)
        except asyncio.CancelledError:
            await _drain(operation)
            raise
        except sqlite3.Error as exc:
            raise ToolFailure("invalid_query" if action.tool == "query_analyze" else "database_unavailable",
                              "Check the owner-granted schema and SELECT syntax/bindings; no query values are disclosed.") from exc
        return self.repo._record({"tool": action.tool, "source_scope": list(task.files), "inspected": [], "data": data}, work=task)
