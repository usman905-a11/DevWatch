"""Interrupt the real post-verification checkpoint without a fake model call."""
import asyncio
from contextlib import contextmanager
from unittest.mock import patch

from devwatch.review.subgraphs import AgentSubgraphs


@contextmanager
def held_assembly(provider, entered, drained=None):
    original = AgentSubgraphs._assemble_verified
    async def hold(runtime, state):
        if runtime.provider is not provider:
            return await original(runtime, state)
        await runtime._save(state)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            if drained is not None:
                drained.set()
    with patch.object(AgentSubgraphs, '_assemble_verified', hold):
        yield
