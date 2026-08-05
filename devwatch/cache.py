import time
import json
import hashlib
from typing import Optional, Dict, Any


class IsolatedResponseCache:
    """Tenant-isolated, prompt-versioned response cache for LLM agent executions."""

    def __init__(self, ttl_seconds: float = 3600.0, max_entries: int = 1000):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: Dict[str, Dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    def _generate_key(
        self, tenant_id: str, prompt_id: str, prompt_version: str, model: str, input_payload: Any
    ) -> str:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Tenant isolation violation: tenant_id required for caching")

        try:
            payload_str = json.dumps(input_payload, sort_keys=True, default=str)
        except Exception:
            payload_str = str(input_payload)

        input_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        raw_key = f"{tenant_id.strip()}:{prompt_id}:{prompt_version}:{model}:{input_hash}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def get(
        self, tenant_id: str, prompt_id: str, prompt_version: str, model: str, input_payload: Any
    ) -> Optional[Any]:
        try:
            key = self._generate_key(tenant_id, prompt_id, prompt_version, model, input_payload)
        except ValueError:
            return None

        entry = self._store.get(key)
        if not entry:
            self.misses += 1
            return None

        if time.time() - entry["created_at"] > self.ttl_seconds:
            del self._store[key]
            self.misses += 1
            return None

        self.hits += 1
        return entry["response"]

    def put(
        self,
        tenant_id: str,
        prompt_id: str,
        prompt_version: str,
        model: str,
        input_payload: Any,
        response: Any,
    ) -> None:
        try:
            key = self._generate_key(tenant_id, prompt_id, prompt_version, model, input_payload)
        except ValueError:
            return

        if len(self._store) >= self.max_entries:
            # Evict oldest entry
            oldest_key = min(self._store.keys(), key=lambda k: self._store[k]["created_at"])
            del self._store[oldest_key]

        self._store[key] = {
            "response": response,
            "created_at": time.time(),
        }

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0
