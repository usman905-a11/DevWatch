import os
import json
import logging
import time
import re
from typing import Optional, Dict, Any, List, Type, TypeVar
from pydantic import BaseModel, ValidationError

from devwatch.config import Config, ModelTier
from devwatch.providers.factory import get_provider
from devwatch.providers.base import LLMRequest, LLMProvider
from devwatch.providers.exceptions import (
    ProviderError,
    ProviderRateLimitError,
    ProviderQuotaExhaustedError,
)
from devwatch.resilience.manager import resilience_manager

logger = logging.getLogger("devwatch.llm")

# Backwards-compatible exception alias for route exception handlers
OpenRouterRateLimitError = ProviderQuotaExhaustedError

T = TypeVar("T", bound=BaseModel)


def is_llm_available(provider: Optional[LLMProvider] = None) -> bool:
    """Check if any LLM API key is set in environment or provider is available."""
    p = provider or get_provider()
    return p.is_available()


def get_llm_model_name(model_tier: ModelTier = ModelTier.HEAVY) -> str:
    """Return configured model name for specified ModelTier."""
    if os.getenv("LLM_MODEL"):
        return os.environ["LLM_MODEL"]
    return Config.get_model_for_tier(model_tier)


def call_llm_completion(
    prompt: str,
    system_prompt: str = "You are an expert AI code auditor.",
    model_tier: ModelTier = ModelTier.HEAVY,
    job_id: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
) -> Optional[str]:
    """Call LLM completion via typed provider abstraction."""
    p = provider or get_provider()
    if not p.is_available():
        return None

    model_name = get_llm_model_name(model_tier)

    req = LLMRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model_name,
        temperature=0.2,
    )

    try:
        response = p.generate_completion_sync(req)
        return response.content
    except (ProviderQuotaExhaustedError, ProviderRateLimitError) as err:
        logger.error(f"Provider Rate/Quota Exceeded: {err}")
        raise
    except ProviderError as err:
        logger.warning(f"LLM completion call failed: {err}")
        return None


async def acall_llm_completion(
    prompt: str,
    system_prompt: str = "You are an expert AI code auditor.",
    model_tier: ModelTier = ModelTier.HEAVY,
    job_id: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
) -> Optional[str]:
    """Asynchronously call LLM completion via typed provider & resilience manager."""
    p = provider or get_provider()
    if not p.is_available():
        return None

    model_name = get_llm_model_name(model_tier)

    req = LLMRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model_name,
        temperature=0.2,
    )

    try:
        response = await resilience_manager.execute_with_resilience(
            func=p.generate_completion,
            request=req,
            job_id=job_id,
            provider_name=getattr(p, "provider_name", "openrouter"),
        )
        return response.content
    except (ProviderQuotaExhaustedError, ProviderRateLimitError) as err:
        logger.error(f"Provider Rate/Quota Exceeded: {err}")
        raise
    except ProviderError as err:
        logger.warning(f"Async LLM completion call failed: {err}")
        return None


def call_llm_structured(
    prompt: str,
    response_model: Type[T],
    system_prompt: str = "You are an expert AI code auditor.",
    max_retries: int = 3,
    model_tier: ModelTier = ModelTier.HEAVY,
    provider: Optional[LLMProvider] = None,
) -> Optional[T]:
    """Call LLM and parse/validate response into Pydantic response_model with self-correction retries."""
    p = provider or get_provider()
    if not p.is_available():
        return None

    current_prompt = prompt
    last_error: Optional[str] = None
    start_time = time.time()
    model_name = get_llm_model_name(model_tier)

    for attempt in range(1, max_retries + 1):
        logger.info(
            f"LLM structured call [Attempt {attempt}/{max_retries}] Target Schema: {response_model.__name__} Model: {model_name}"
        )

        response_text = call_llm_completion(current_prompt, system_prompt=system_prompt, model_tier=model_tier, provider=p)
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
    provider: Optional[LLMProvider] = None,
) -> Optional[T]:
    """Asynchronously call LLM and parse/validate response into Pydantic model with self-correction retries."""
    p = provider or get_provider()
    if not p.is_available():
        return None

    current_prompt = prompt
    last_error: Optional[str] = None
    start_time = time.time()
    model_name = get_llm_model_name(model_tier)

    for attempt in range(1, max_retries + 1):
        logger.info(
            f"Async LLM structured call [Attempt {attempt}/{max_retries}] Target Schema: {response_model.__name__} Model: {model_name}"
        )

        response_text = await acall_llm_completion(current_prompt, system_prompt=system_prompt, model_tier=model_tier, provider=p)
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
    """Clean reasoning tags (<think>...</think>), markdown code fences, and extract valid JSON from LLM response."""
    if not response:
        return None
    cleaned = response.strip()

    # Strip thinking/chain-of-thought blocks output by reasoning models like DeepSeek R1
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

    # Extract JSON inside code blocks if present
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if json_match:
        cleaned = json_match.group(1).strip()
    else:
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
