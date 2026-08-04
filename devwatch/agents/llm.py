import os
import json
import logging
from typing import Optional, Dict, Any, List

from devwatch.config import Config, ModelTier

logger = logging.getLogger("devwatch.llm")


def is_llm_available() -> bool:
    """Check if any LLM API key is set in environment."""
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("GROQ_API_KEY")
    )


def get_llm_model_name(model_tier: ModelTier = ModelTier.HEAVY) -> str:
    """Return configured model name for specified ModelTier."""
    if os.getenv("LLM_MODEL"):
        return os.environ["LLM_MODEL"]
    return Config.get_model_for_tier(model_tier)


def call_llm_completion(
    prompt: str,
    system_prompt: str = "You are an expert AI code auditor.",
    model_tier: ModelTier = ModelTier.HEAVY,
) -> Optional[str]:
    """Call LLM completion directly via OpenAI / LiteLLM API client if available."""
    if not is_llm_available():
        return None

    model_name = get_llm_model_name(model_tier)
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


async def acall_llm_completion(
    prompt: str,
    system_prompt: str = "You are an expert AI code auditor.",
    model_tier: ModelTier = ModelTier.HEAVY,
) -> Optional[str]:
    """Async wrapper for LLM completion API call."""
    if not is_llm_available():
        return None

    model_name = get_llm_model_name(model_tier)
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("GROQ_API_KEY")
    )

    try:
        import openai
        if hasattr(openai, "AsyncOpenAI"):
            client = openai.AsyncOpenAI(api_key=api_key)
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content
        return await asyncio.to_thread(call_llm_completion, prompt, system_prompt)
    except Exception as err:
        logger.warning(f"Async LLM completion call failed, falling back to thread: {err}")
        return await asyncio.to_thread(call_llm_completion, prompt, system_prompt)



import time
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


import inspect


def _safe_call_completion(func, prompt: str, system_prompt: str, model_tier: ModelTier):
    """Safely call completion function checking if model_tier kwarg is accepted."""
    try:
        sig = inspect.signature(func)
        if "model_tier" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return func(prompt, system_prompt=system_prompt, model_tier=model_tier)
    except (ValueError, TypeError):
        pass
    return func(prompt, system_prompt=system_prompt)


async def _asafe_call_completion(func, prompt: str, system_prompt: str, model_tier: ModelTier):
    """Safely await completion function checking if model_tier kwarg is accepted."""
    try:
        sig = inspect.signature(func)
        if "model_tier" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return await func(prompt, system_prompt=system_prompt, model_tier=model_tier)
    except (ValueError, TypeError):
        pass
    return await func(prompt, system_prompt=system_prompt)


def call_llm_structured(
    prompt: str,
    response_model: Type[T],
    system_prompt: str = "You are an expert AI code auditor.",
    max_retries: int = 3,
    model_tier: ModelTier = ModelTier.HEAVY,
) -> Optional[T]:
    """Call LLM and parse/validate response into Pydantic response_model with self-correction retries."""
    if not is_llm_available():
        return None

    current_prompt = prompt
    last_error: Optional[str] = None
    start_time = time.time()
    model_name = get_llm_model_name(model_tier)

    for attempt in range(1, max_retries + 1):
        logger.info(
            f"LLM structured call [Attempt {attempt}/{max_retries}] Target Schema: {response_model.__name__} Model: {model_name}"
        )

        response_text = _safe_call_completion(call_llm_completion, current_prompt, system_prompt, model_tier)
        if not response_text:
            logger.warning(f"Attempt {attempt}: Received empty completion from LLM provider")
            continue

        try:
            raw_data = parse_llm_json(response_text)
            if raw_data is None:
                raise ValueError("JSON parsing returned None or empty string")

            # Handle case where LLM returns a JSON list directly when wrapping object expected
            if isinstance(raw_data, list) and ("issues" in getattr(response_model, "model_fields", {})):
                validated_obj = response_model.model_validate({"issues": raw_data})
            elif isinstance(raw_data, dict):
                validated_obj = response_model.model_validate(raw_data)
            else:
                validated_obj = response_model.model_validate(raw_data)

            duration = time.time() - start_time
            logger.info(
                f"LLM structured call succeeded in {duration:.2f}s [Attempt {attempt}/{max_retries}] Schema: {response_model.__name__}"
            )
            return validated_obj

        except (ValidationError, ValueError, json.JSONDecodeError) as err:
            last_error = str(err)
            logger.warning(
                f"Attempt {attempt}/{max_retries} failed schema validation for {response_model.__name__}: {last_error}"
            )
            current_prompt = (
                f"{prompt}\n\n"
                f"[SYSTEM FEEDBACK: Your previous JSON response failed Pydantic schema validation for '{response_model.__name__}'.]\n"
                f"Validation Error Details:\n{last_error}\n\n"
                f"Please fix your JSON formatting and return ONLY a valid JSON object matching the exact schema."
            )

    logger.error(
        f"All {max_retries} LLM structured attempts failed for {response_model.__name__}. Last Error: {last_error}"
    )
    return None


async def acall_llm_structured(
    prompt: str,
    response_model: Type[T],
    system_prompt: str = "You are an expert AI code auditor.",
    max_retries: int = 3,
    model_tier: ModelTier = ModelTier.HEAVY,
) -> Optional[T]:
    """Asynchronously call LLM and parse/validate response into Pydantic model with self-correction retries."""
    if not is_llm_available():
        return None

    current_prompt = prompt
    last_error: Optional[str] = None
    start_time = time.time()
    model_name = get_llm_model_name(model_tier)

    for attempt in range(1, max_retries + 1):
        logger.info(
            f"Async LLM structured call [Attempt {attempt}/{max_retries}] Target Schema: {response_model.__name__} Model: {model_name}"
        )

        response_text = await _asafe_call_completion(acall_llm_completion, current_prompt, system_prompt, model_tier)
        if not response_text:
            logger.warning(f"Attempt {attempt}: Received empty completion from LLM provider")
            continue

        try:
            raw_data = parse_llm_json(response_text)
            if raw_data is None:
                raise ValueError("JSON parsing returned None or empty string")

            if isinstance(raw_data, list) and ("issues" in getattr(response_model, "model_fields", {})):
                validated_obj = response_model.model_validate({"issues": raw_data})
            elif isinstance(raw_data, dict):
                validated_obj = response_model.model_validate(raw_data)
            else:
                validated_obj = response_model.model_validate(raw_data)

            duration = time.time() - start_time
            logger.info(
                f"Async LLM structured call succeeded in {duration:.2f}s [Attempt {attempt}/{max_retries}] Schema: {response_model.__name__}"
            )
            return validated_obj

        except (ValidationError, ValueError, json.JSONDecodeError) as err:
            last_error = str(err)
            logger.warning(
                f"Attempt {attempt}/{max_retries} failed schema validation for {response_model.__name__}: {last_error}"
            )
            current_prompt = (
                f"{prompt}\n\n"
                f"[SYSTEM FEEDBACK: Your previous JSON response failed Pydantic schema validation for '{response_model.__name__}'.]\n"
                f"Validation Error Details:\n{last_error}\n\n"
                f"Please fix your JSON formatting and return ONLY a valid JSON object matching the exact schema."
            )

    logger.error(
        f"All {max_retries} async LLM structured attempts failed for {response_model.__name__}. Last Error: {last_error}"
    )
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

