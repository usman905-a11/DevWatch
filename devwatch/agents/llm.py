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


def call_llm_completion(prompt: str, system_prompt: str = "You are an expert AI code auditor.") -> Optional[str]:
    """Call LLM completion directly via OpenAI / LiteLLM API client if available."""
    if not is_llm_available():
        return None

    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("GROQ_API_KEY")
    )

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content
    except Exception as err:
        logger.warning(f"LLM completion call failed: {err}")

    return None



def parse_llm_json(response: str) -> Any:
    """Clean markdown code fences and parse JSON from LLM response."""
    if not response:
        return None
    cleaned = response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return json.loads(cleaned.strip())


def add_line_numbers(code: str) -> str:
    """Prepend 1-indexed line numbers to code string for exact LLM line targeting."""
    if not code:
        return ""
    lines = code.splitlines()
    return "\n".join(f"{i:4d} | {line}" for i, line in enumerate(lines, 1))

