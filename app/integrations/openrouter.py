"""OpenAI-compatible transport and safe completion diagnostics."""
import json
import logging
import math
import re
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

LOG = logging.getLogger("ml-trainer.trainer")


def current_key_budget(settings):
    endpoint = urlsplit(settings.completion_url)
    if not settings.completion_key or endpoint.scheme != "https" or endpoint.hostname != "openrouter.ai":
        return {"available": False, "reason": "not_configured"}
    try:
        response = httpx.get("https://openrouter.ai/api/v1/key",
                             headers={"Authorization": f"Bearer {settings.completion_key}"},
                             proxy=settings.completion_proxy, timeout=5)
        response.raise_for_status()
        data = response.json()["data"]
        amounts = {field: data.get(field) for field in ("limit", "limit_remaining", "usage_daily")}
        if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value))
               for value in amounts.values()):
            raise ValueError("Invalid budget metadata")
        reset = data.get("limit_reset")
        return {"available": True, **amounts, "limit_reset": reset if reset in ("daily", "weekly", "monthly") else None}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return {"available": False, "reason": "unavailable"}


def _label(value):
    """Only log short identifiers, never arbitrary provider text or user content."""
    if isinstance(value, (str, int)) and re.fullmatch(r"[\w.:/\-]{1,160}", str(value), flags=re.ASCII):
        return value
    return None


def completion_content(response, operation, model, parse):
    details = {"operation": operation, "model": _label(model), "http_status": response.status_code}
    try:
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Completion must be an object")
        details["generation_id"] = _label(data.get("id"))
        details["provider"] = _label(data.get("provider"))
        choice = data["choices"][0]
        details["finish_reason"] = _label(choice.get("finish_reason"))
        details["native_finish_reason"] = _label(choice.get("native_finish_reason"))
        usage = data.get("usage")
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if isinstance(usage.get(key), int):
                    details[key] = usage[key]
        content = choice["message"]["content"]
        details["content_length"] = len(content) if isinstance(content, str) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Completion content is empty or not text")
        return parse(content)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        details["error_type"] = type(error).__name__
        if isinstance(error, ValidationError):
            # Pydantic error messages can contain the entire answer; retain only field/type.
            details["validation"] = [{"field": ".".join(map(str, item["loc"])), "type": item["type"]}
                                     for item in error.errors(include_input=False, include_context=False)]
        LOG.warning("Model response rejected: %s", json.dumps(details, ensure_ascii=True))
        raise


def log_model_failure(operation, model, question_id, error):
    # Do not log exception text, request bodies, authorization headers, or raw model replies.
    LOG.warning("Model call failed: operation=%s model=%s question_id=%s error_type=%s http_status=%s",
                operation, _label(model), question_id, type(error).__name__,
                error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None)


def completion_payload(settings, model, messages, *, max_tokens, json_mode):
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if settings.llm_base_url in ("https://api.deepseek.com", "https://api.deepseek.com/v1"):
        payload["thinking"] = {"type": "disabled"}
    return payload


def chat_completion(settings, messages, *, operation, parse, json_mode=False, max_tokens=2000, model=None):
    """Send one completion and parse it without logging private content."""
    model = model or settings.trainer_model_name
    with httpx.Client(timeout=90, proxy=settings.completion_proxy) as client:
        response = client.post(
            settings.completion_url,
            headers={"Authorization": f"Bearer {settings.completion_key}"},
            json=completion_payload(settings, model, messages, max_tokens=max_tokens, json_mode=json_mode),
        )
        return completion_content(response, operation, model, parse)
