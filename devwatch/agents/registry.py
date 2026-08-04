from typing import Dict, List, Optional
from devwatch.agents.base import BaseAgent, AgentMetadata


class AgentRegistry:
    """Centralized registry for managing agent instances and metadata."""

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """Register an agent instance."""
        meta = agent.metadata
        self._agents[meta.agent_id] = agent

    def get(self, agent_id: str) -> BaseAgent:
        """Retrieve registered agent by agent_id."""
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' is not registered in AgentRegistry.")
        return self._agents[agent_id]

    def list_agents(self) -> List[AgentMetadata]:
        """List metadata for all registered agents."""
        return [agent.metadata for agent in self._agents.values()]

    def clear(self) -> None:
        """Clear all registered agents (useful for test resets)."""
        self._agents.clear()


agent_registry = AgentRegistry()
