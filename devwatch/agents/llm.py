import os
import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("devwatch.llm")


def is_llm_available() -> bool:
    """Check if any LLM API key is set in environment."""
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("GROQ_API_KEY")
    )


def get_llm_model_name() -> str:
    """Return configured model name or default."""
    if os.getenv("LLM_MODEL"):
        return os.environ["LLM_MODEL"]
    if os.getenv("GEMINI_API_KEY"):
        return "gemini/gemini-1.5-flash"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude-3-5-sonnet-20240620"
    return "gpt-4o-mini"


def get_crewai_llm():
    """Instantiate a CrewAI LLM instance if configured, else returns None."""
    if not is_llm_available():
        return None

    model_name = get_llm_model_name()
    try:
        from crewai import LLM
        return LLM(model=model_name)
    except Exception as e:
        logger.warning(f"Could not initialize CrewAI LLM ({model_name}): {e}")
        return None


def call_llm_completion(prompt: str, system_prompt: str = "You are an expert AI code auditor.") -> Optional[str]:
    """Call LLM directly via CrewAI LLM or OpenAI/LiteLLM client if available."""
    if not is_llm_available():
        return None

    # Try CrewAI LLM completion first
    try:
        from crewai import LLM
        model_name = get_llm_model_name()
        llm = LLM(model=model_name)
        response = llm.call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
        )
        if response:
            return str(response)
    except Exception as err:
        logger.warning(f"CrewAI LLM call failed: {err}")

    # Fallback to direct openai client if available
    if os.getenv("OPENAI_API_KEY"):
        try:
            import openai
            client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            response = client.chat.completions.create(
                model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            return response.choices[0].message.content
        except Exception as err:
            logger.warning(f"Direct OpenAI client call failed: {err}")

    return None
