"""
DevWatch Agents Package
"""

from devwatch.agents.base import BaseAgent, AgentMetadata
from devwatch.agents.registry import agent_registry, AgentRegistry
from devwatch.agents.fake_agent import FakeAgent
from devwatch.agents.planner import PlannerAgent
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.verifier import VerificationAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent

__all__ = [
    "BaseAgent",
    "AgentMetadata",
    "agent_registry",
    "AgentRegistry",
    "FakeAgent",
    "PlannerAgent",
    "SecurityAuditorAgent",
    "QualityAuditorAgent",
    "VerificationAgent",
    "ReportSynthesizerAgent",
]
