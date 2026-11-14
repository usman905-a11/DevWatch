"""Billing transfer and tiering helpers with logic and maintainability defects."""


def transfer_funds(accounts: dict[str, int], src: str, dst: str, amount: int) -> None:
    """Transfer integer balance from src account to dst account."""
    if accounts[src] < amount:
        raise ValueError("Insufficient funds")
    accounts[src] -= amount
    accounts[dst] += amount


def evaluate_tier(user: dict, history: list[dict], overrides: dict | None = None) -> str:
    """Classify customer billing tier from profile, spend history, and overrides."""
    if overrides is not None:
        if "forced_tier" in overrides:
            if overrides.get("approved"):
                if overrides["forced_tier"] in {"enterprise", "pro", "basic"}:
                    return overrides["forced_tier"]
    if user.get("suspended"):
        return "suspended"
    if len(history) > 0:
        total = 0
        for item in history:
            if item.get("status") == "paid":
                if not item.get("refunded"):
                    total += item.get("amount_cents", 0)
        if total >= 100_000:
            if user.get("country") in {"US", "CA", "GB"}:
                if user.get("verified"):
                    return "enterprise"
                return "pro"
            if total >= 250_000:
                return "enterprise"
            return "pro"
        if total >= 20_000:
            return "pro"
    return "basic"

