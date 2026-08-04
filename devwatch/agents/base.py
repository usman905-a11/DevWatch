from abc import ABC, abstractmethod
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field


class AgentMetadata(BaseModel):
    agent_id: str
    version: str = "1.0.0"
    purpose: str
    prompt_id: str
    prompt_version: str = "1.0.0"
    input_schema: Optional[str] = None
    output_schema: Optional[str] = None


class BaseAgent(ABC):
    """Abstract Base Class for all DevWatch agents."""

    @property
    @abstractmethod
    def metadata(self) -> AgentMetadata:
        """Return structured metadata describing this agent."""
        pass

    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> Any:
        """Single canonical async execution method for the agent.

        Args:
            context: Dictionary containing input parameters for execution
                     (e.g., target_path, file_path, code_content, etc.)

        Returns:
            Structured output model or result domain object.
        """
        pass
