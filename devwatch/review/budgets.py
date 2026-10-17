"""Deterministic cumulative job accounting; serialize the ledger with job state.

All reservations count against admission, including unresolved provider calls.
The service also owns a global model-call semaphore; this manager guards one job.
"""

import math
import threading
import time
from typing import Callable
from uuid import uuid4

from pydantic import Field, field_validator

from devwatch.review.contracts import AgentId, BalancedLimits, ContractModel, TokenUsage


class BudgetExceeded(RuntimeError):
    pass


class ModelReservation(ContractModel):
    agent_id: AgentId
    tokens: int = Field(ge=1)


class BudgetLedger(ContractModel):
    review_round: int = Field(default=1, ge=1, le=2)
    agent_usage: dict[AgentId, TokenUsage] = Field(default_factory=dict)
    inflight: dict[str, ModelReservation] = Field(default_factory=dict)
    task_iterations: dict[str, int] = Field(default_factory=dict)
    task_tools: dict[str, int] = Field(default_factory=dict)
    task_schema_repairs: dict[str, int] = Field(default_factory=dict)
    operation_retries: dict[str, int] = Field(default_factory=dict)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)

    @field_validator("task_iterations", "task_tools", "task_schema_repairs", "operation_retries")
    @classmethod
    def nonnegative_counters(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("cumulative counters must not be negative")
        return value

    @property
    def total_tokens(self) -> int:
        return sum(usage.total_tokens for usage in self.agent_usage.values())


class BudgetManager:
    def __init__(self, limits: BalancedLimits | None = None, ledger: BudgetLedger | None = None, *,
                 clock: Callable[[], float] = time.monotonic):
        self.limits = limits or BalancedLimits()
        self.ledger = ledger or BudgetLedger()
        self._lock = threading.RLock()
        self._clock = clock
        self._execution_start: float | None = None
        self._initial_elapsed = self.ledger.elapsed_seconds

    def begin_execution(self) -> None:
        with self._lock:
            if self._execution_start is None:
                self._initial_elapsed = self.ledger.elapsed_seconds
                self._execution_start = self._clock()

    def refresh_time(self) -> None:
        with self._lock:
            if self._execution_start is not None:
                elapsed = self._initial_elapsed + max(0, self._clock() - self._execution_start)
                self.ledger.elapsed_seconds = max(self.ledger.elapsed_seconds, elapsed)

    def _ensure_time(self) -> None:
        self.refresh_time()
        if self.ledger.elapsed_seconds >= self.limits.review_seconds:
            raise BudgetExceeded("review time exhausted")

    def _agent_ceiling(self, agent: AgentId) -> int:
        if agent == AgentId.PLANNER:
            return self.limits.planner_tokens
        if agent == AgentId.SYNTHESIZER_VERIFIER:
            return self.limits.final_agent_tokens
        return self.limits.specialist_tokens

    def reserve_model(self, agent: AgentId, tokens: int) -> str:
        reservation = ModelReservation(agent_id=agent, tokens=tokens)
        with self._lock:
            self._ensure_time()
            if len(self.ledger.inflight) >= self.limits.concurrent_model_calls:
                raise BudgetExceeded("concurrent model call limit reached")
            agent_spent = self.ledger.agent_usage.get(agent, TokenUsage()).total_tokens
            agent_reserved = sum(r.tokens for r in self.ledger.inflight.values() if r.agent_id == agent)
            if agent_spent + agent_reserved + tokens > self._agent_ceiling(agent):
                raise BudgetExceeded("agent token ceiling reached")
            pending = sum(r.tokens for r in self.ledger.inflight.values())
            if self.ledger.total_tokens + pending + tokens > self.limits.job_tokens:
                raise BudgetExceeded("job token ceiling reached")
            if agent != AgentId.SYNTHESIZER_VERIFIER:
                final_spent = self.ledger.agent_usage.get(AgentId.SYNTHESIZER_VERIFIER, TokenUsage()).total_tokens
                final_pending = sum(r.tokens for r in self.ledger.inflight.values()
                                    if r.agent_id == AgentId.SYNTHESIZER_VERIFIER)
                reserve_remaining = max(0, self.limits.final_agent_tokens - final_spent - final_pending)
                if self.ledger.total_tokens + pending + tokens + reserve_remaining > self.limits.job_tokens:
                    raise BudgetExceeded("final agent tokens are reserved")
            ticket = uuid4().hex
            self.ledger.inflight[ticket] = reservation
            return ticket

    def record_model(self, ticket: str, *, prompt_tokens: int, completion_tokens: int) -> None:
        usage = TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        with self._lock:
            reservation = self.ledger.inflight.pop(ticket)
            previous = self.ledger.agent_usage.get(reservation.agent_id, TokenUsage())
            self.ledger.agent_usage[reservation.agent_id] = TokenUsage(
                prompt_tokens=previous.prompt_tokens + usage.prompt_tokens,
                completion_tokens=previous.completion_tokens + usage.completion_tokens,
            )
            # Actual provider consumption remains accounted even if it violates admission.
            if usage.total_tokens > reservation.tokens:
                raise BudgetExceeded("provider exceeded token reservation")

    def _consume(self, counters: dict[str, int], identity: str, ceiling: int, label: str) -> None:
        with self._lock:
            self._ensure_time()
            count = counters.get(identity, 0)
            if count >= ceiling:
                raise BudgetExceeded(f"{label} limit reached")
            counters[identity] = count + 1

    def consume_tool(self, task_id: str) -> None:
        self._consume(self.ledger.task_tools, task_id, self.limits.tool_calls_per_task, "tool calls")

    def consume_iteration(self, task_id: str) -> None:
        self._consume(self.ledger.task_iterations, task_id, self.limits.iterations_per_task, "iterations")

    def consume_schema_repair(self, task_id: str) -> None:
        self._consume(self.ledger.task_schema_repairs, task_id, self.limits.schema_repairs_per_task, "schema repairs")

    def consume_retry(self, operation_id: str, *, replay_safe: bool) -> None:
        if not replay_safe:
            raise PermissionError("unknown operation completion cannot be retried")
        self._consume(self.ledger.operation_retries, operation_id, self.limits.transient_retries, "retries")

    def admit_followup(self) -> None:
        with self._lock:
            self._ensure_time()
            if self.ledger.review_round >= self.limits.review_rounds:
                raise BudgetExceeded("review round limit reached")
            self.ledger.review_round += 1

    def consume_time(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("elapsed time must be finite and nonnegative")
        with self._lock:
            self.ledger.elapsed_seconds += seconds

    def timeout_for(self, operation: str) -> float:
        with self._lock:
            self._ensure_time()
            if operation == "provider":
                ceiling = self.limits.provider_timeout_seconds
            elif operation == "command":
                ceiling = self.limits.command_timeout_seconds
            else:
                raise ValueError("unknown timeout operation")
            return min(ceiling, self.limits.review_seconds - self.ledger.elapsed_seconds)
