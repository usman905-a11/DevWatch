from typing import Dict, Any, Optional
from devwatch.agents.base import BaseAgent, AgentMetadata


class FakeAgent(BaseAgent):
    """Fake Agent implementation for offline testing and substitution."""

    def __init__(
        self,
        agent_id: str = "fake_agent",
        version: str = "1.0.0",
        purpose: str = "Fake agent for testing",
        canned_output: Optional[Any] = None,
    ):
        self._metadata = AgentMetadata(
            agent_id=agent_id,
            version=version,
            purpose=purpose,
            prompt_id=f"{agent_id}:v1",
            prompt_version="1.0.0",
        )
        self.canned_output = canned_output if canned_output is not None else {"status": "ok", "message": "Fake agent output"}

        self.executed_contexts = []

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    async def execute(self, context: Dict[str, Any]) -> Any:
        self.executed_contexts.append(context)
        return self.canned_output
