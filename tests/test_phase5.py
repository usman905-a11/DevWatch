import os
import pytest
from unittest.mock import patch
from devwatch.config import Config, ModelTier
from devwatch.agents.llm import get_llm_model_name, call_llm_structured
from devwatch.agents.planner import PlannerAgent
from devwatch.agents.verifier import VerificationAgent
from devwatch.models import StructuredPlannerResponse, CodeIssue, IssueSeverity


def test_model_tier_config_defaults():
    with patch.dict(os.environ, {}, clear=True):
        assert Config.get_model_for_tier(ModelTier.FAST) == "gpt-4o-mini"
        assert Config.get_model_for_tier(ModelTier.HEAVY) == "gpt-4o"


def test_model_tier_env_override():
    with patch.dict(os.environ, {"DEVWATCH_FAST_MODEL": "custom-fast-model", "DEVWATCH_HEAVY_MODEL": "custom-heavy-model"}):
        assert Config.get_model_for_tier(ModelTier.FAST) == "custom-fast-model"
        assert Config.get_model_for_tier(ModelTier.HEAVY) == "custom-heavy-model"


def test_get_llm_model_name_routing():
    with patch.dict(os.environ, {}, clear=True):
        assert get_llm_model_name(ModelTier.FAST) == "gpt-4o-mini"
        assert get_llm_model_name(ModelTier.HEAVY) == "gpt-4o"



def test_planner_agent_uses_fast_tier():
    with patch("devwatch.agents.llm.is_llm_available", return_value=True):
        with patch("devwatch.agents.llm.acall_llm_structured") as mock_structured:
            mock_structured.return_value = StructuredPlannerResponse(priority_files=[], focus_areas=[])
            planner = PlannerAgent()
            planner.plan_review(os.path.dirname(os.path.abspath(__file__)))

            assert mock_structured.called
            assert mock_structured.call_args.kwargs.get("model_tier") == ModelTier.FAST

