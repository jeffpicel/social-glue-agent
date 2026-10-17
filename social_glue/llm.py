"""Crusoe Managed Inference client. Falls back to a fake LLM when no key is set (FAKE_LLM=1 forces it)."""
import json
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Running total of prompt tokens, read by score.py for the "cost" metric.
USAGE = {"calls": 0, "prompt_tokens": 0}

_client = None


def is_fake() -> bool:
    return os.getenv("FAKE_LLM") == "1" or not os.getenv("CRUSOE_API_KEY")


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        base_url = os.getenv("CRUSOE_BASE_URL") or "https://api.inference.crusoecloud.com/v1"
        _client = OpenAI(api_key=os.environ["CRUSOE_API_KEY"], base_url=base_url)
    return _client


def _model(tier: str) -> str:
    if tier == "strong":
        return os.getenv("CRUSOE_MODEL_STRONG") or "deepseek-ai/DeepSeek-V4-Pro"
    return os.getenv("CRUSOE_MODEL_FAST") or "deepseek-ai/DeepSeek-V4-Flash"


def chat(system: str, user: str, tier: str = "strong", json_mode: bool = False, fake=None):
    """One model call. Returns a string, or a parsed dict/list when json_mode is set.

    `fake` is a zero-arg callable used in fake mode so each agent can supply a sensible canned answer.
    """
    USAGE["calls"] += 1
    if is_fake():
        USAGE["prompt_tokens"] += (len(system) + len(user)) // 4
        out = fake() if fake else ("{}" if json_mode else "")
        return out if not isinstance(out, str) or not json_mode else json.loads(out)

    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        resp = _get_client().chat.completions.create(model=_model(tier), messages=messages, temperature=0.4, **kwargs)
    except Exception:  # noqa: BLE001 - some models reject response_format; retry once without it
        if not kwargs:
            raise
        resp = _get_client().chat.completions.create(model=_model(tier), messages=messages, temperature=0.4)
    if resp.usage:
        USAGE["prompt_tokens"] += resp.usage.prompt_tokens
    text = resp.choices[0].message.content or ""
    if not json_mode:
        return text.strip()
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start : end + 1] if start >= 0 else text)
    except json.JSONDecodeError:
        return {}
