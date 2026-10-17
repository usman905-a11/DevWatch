"""Offline browser-test service; never select this as a production provider."""
import asyncio
import os
from pathlib import Path

from devwatch.review.service import ServiceSettings, create_app
from tests.test_canonical_workflow import ReviewProvider
from tests.test_control_agents import MODELS


class BrowserProvider(ReviewProvider):
    async def generate_completion(self, request):
        # Make the durable-running/disconnect case observable without live models.
        await asyncio.sleep(.4)
        return await super().generate_completion(request)


def app():
    root = Path(os.environ['DEVWATCH_UI_TEST_ROOT'])
    return create_app(provider=BrowserProvider(), settings=ServiceSettings(
        runtime_root=root, models=MODELS, api_keys=frozenset({'browser-fixture-key'})))


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app(), host='127.0.0.1', port=8019, log_level='warning')
