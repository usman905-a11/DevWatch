"""Budget limits must survive retries, restored state and targeted follow-up."""

import importlib

import pytest

from devwatch.review.contracts import AgentId, BalancedLimits


def budgets():
    assert importlib.util.find_spec("devwatch.review.budgets"), "Cumulative budget manager is missing"
    return importlib.import_module("devwatch.review.budgets")


def test_specialists_cannot_spend_final_agent_reserve():
    api = budgets()
    limits = BalancedLimits(job_tokens=100, final_agent_tokens=30, specialist_tokens=100)
    manager = api.BudgetManager(limits)
    reservation = manager.reserve_model(AgentId.BUG_RELIABILITY, 70)
    manager.record_model(reservation, prompt_tokens=50, completion_tokens=20)
    with pytest.raises(api.BudgetExceeded, match="reserved"):
        manager.reserve_model(AgentId.LOGIC_CORRECTNESS, 1)
    final = manager.reserve_model(AgentId.SYNTHESIZER_VERIFIER, 30)
    manager.record_model(final, prompt_tokens=20, completion_tokens=10)
    assert manager.ledger.total_tokens == 100


def test_three_inflight_model_reservations_and_no_fourth():
    api = budgets()
    manager = api.BudgetManager()
    tickets = [manager.reserve_model(AgentId.BUG_RELIABILITY, 100) for _ in range(3)]
    with pytest.raises(api.BudgetExceeded, match="concurrent"):
        manager.reserve_model(AgentId.LOGIC_CORRECTNESS, 100)
    manager.record_model(tickets[0], prompt_tokens=20, completion_tokens=10)
    assert manager.reserve_model(AgentId.LOGIC_CORRECTNESS, 100)


def test_restored_task_does_not_reset_tool_iteration_repair_or_retry_limits():
    api = budgets()
    manager = api.BudgetManager()
    for _ in range(12):
        manager.consume_tool("task-1")
    for _ in range(8):
        manager.consume_iteration("task-1")
    manager.consume_schema_repair("task-1")
    for _ in range(2):
        manager.consume_retry("operation-1", replay_safe=True)
    saved = manager.ledger.model_dump(mode="json")
    resumed = api.BudgetManager(ledger=api.BudgetLedger.model_validate(saved))
    for action, args in ((resumed.consume_tool, ("task-1",)),
                         (resumed.consume_iteration, ("task-1",)),
                         (resumed.consume_schema_repair, ("task-1",))):
        with pytest.raises(api.BudgetExceeded):
            action(*args)
    with pytest.raises(api.BudgetExceeded):
        resumed.consume_retry("operation-1", replay_safe=True)
    with pytest.raises(PermissionError):
        resumed.consume_retry("unknown-command", replay_safe=False)


def test_specialist_ceiling_is_cumulative_across_tasks():
    api = budgets()
    manager = api.BudgetManager()
    first = manager.reserve_model(AgentId.PERFORMANCE_SCALABILITY, 30_000)
    manager.record_model(first, prompt_tokens=25_000, completion_tokens=5_000)
    second = manager.reserve_model(AgentId.PERFORMANCE_SCALABILITY, 20_000)
    manager.record_model(second, prompt_tokens=15_000, completion_tokens=5_000)
    with pytest.raises(api.BudgetExceeded, match="agent"):
        manager.reserve_model(AgentId.PERFORMANCE_SCALABILITY, 1)


def test_inflight_tokens_and_consumed_time_survive_restore():
    api = budgets()
    manager = api.BudgetManager(BalancedLimits(job_tokens=100, final_agent_tokens=20))
    manager.reserve_model(AgentId.BUG_RELIABILITY, 80)
    manager.consume_time(590)
    restored = api.BudgetManager(manager.limits, api.BudgetLedger.model_validate(manager.ledger.model_dump()))
    with pytest.raises(api.BudgetExceeded):
        restored.reserve_model(AgentId.LOGIC_CORRECTNESS, 1)
    assert restored.timeout_for("provider") == 10
    restored.consume_time(10)
    with pytest.raises(api.BudgetExceeded, match="time"):
        restored.consume_iteration("t1")


def test_provider_overrun_is_accounted_and_stops_further_calls():
    api = budgets()
    manager = api.BudgetManager(BalancedLimits(job_tokens=100, final_agent_tokens=20))
    ticket = manager.reserve_model(AgentId.BUG_RELIABILITY, 60)
    with pytest.raises(api.BudgetExceeded, match="reservation"):
        manager.record_model(ticket, prompt_tokens=100, completion_tokens=10)
    assert manager.ledger.total_tokens == 110
    with pytest.raises(api.BudgetExceeded):
        manager.reserve_model(AgentId.SYNTHESIZER_VERIFIER, 1)


def test_execution_clock_counts_wall_time_once_and_resumes_from_spent_time():
    api = budgets()
    now = [100.0]
    manager = api.BudgetManager(clock=lambda: now[0])
    manager.begin_execution()
    now[0] += 10
    manager.refresh_time()
    manager.refresh_time()
    assert manager.ledger.elapsed_seconds == 10
    saved = api.BudgetLedger.model_validate(manager.ledger.model_dump())
    now[0] = 1000
    resumed = api.BudgetManager(ledger=saved, clock=lambda: now[0])
    resumed.begin_execution()
    now[0] += 5
    assert resumed.timeout_for("provider") == 30
    assert resumed.ledger.elapsed_seconds == 15
