"""Model client. Crusoe Managed Inference by default; LLM_PROVIDER=anthropic switches to Claude.
Falls back to a fake LLM when the chosen provider has no key (FAKE_LLM=1 forces it)."""
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


def _provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "crusoe").lower()


def is_fake() -> bool:
    key = "ANTHROPIC_API_KEY" if _provider() == "anthropic" else "CRUSOE_API_KEY"
    return os.getenv("FAKE_LLM") == "1" or not os.getenv(key)


def _anthropic_text(system: str, user: str, tier: str, json_mode: bool):
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    model = os.getenv("ANTHROPIC_MODEL_STRONG" if tier == "strong" else "ANTHROPIC_MODEL_FAST") or (
        "claude-sonnet-5-5" if tier == "strong" else "claude-haiku-5-5")
    if json_mode:
        system += "\n\nRespond with a single JSON object and nothing else."
    resp = _client.messages.create(model=model, max_tokens=1024, system=system,
                                   messages=[{"role": "user", "content": user}])
    USAGE["prompt_tokens"] += resp.usage.input_tokens
    return "".join(b.text for b in resp.content if b.type == "text")


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
    return os.getenv("CRUSOE_MODEL_FAST") or "deepseek-ai/Deepseek-V4-Flash"


def chat(system: str, user: str, tier: str = "strong", json_mode: bool = False, fake=None):
    """One model call. Returns a string, or a parsed dict/list when json_mode is set.

    `fake` is a zero-arg callable used in fake mode so each agent can supply a sensible canned answer.
    """
    USAGE["calls"] += 1
    if is_fake():
        USAGE["prompt_tokens"] += (len(system) + len(user)) // 4
        out = fake() if fake else ("{}" if json_mode else "")
        return out if not isinstance(out, str) or not json_mode else json.loads(out)

    if _provider() == "anthropic":
        text = _anthropic_text(system, user, tier, json_mode)
        return _parse(text, json_mode)

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
    return _parse(resp.choices[0].message.content or "", json_mode)


def _parse(text: str, json_mode: bool):
    if not json_mode:
        return text.strip()
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start : end + 1] if start >= 0 else text)
    except json.JSONDecodeError:
        return {}
