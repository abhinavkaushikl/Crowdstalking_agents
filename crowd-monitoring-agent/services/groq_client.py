"""
Thin wrapper over Groq's OpenAI-compatible chat/completions endpoint, plus
the standard tool-calling loop (request -> tool_calls -> execute locally ->
feed results back -> repeat -> final answer).

openai/gpt-oss-* models on Groq are reasoning models: they spend tokens on an
internal "reasoning" field before the final "content" - max_tokens has to
budget for both, or the response comes back empty with finish_reason:"length"
(confirmed live in the Node version: max_tokens=20 produced zero content, all
20 tokens went to reasoning).
"""
import json
import os
import re
import time

import requests

from tools.registry import AgentTrace, ToolRegistry
from utils.config_loader import get as config_get

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("GROQ_MODEL") or config_get("groq.default_model", "openai/gpt-oss-120b")
DEFAULT_MAX_TOKENS = config_get("groq.default_max_tokens", 2000)
MAX_TOOL_ROUNDS = config_get("groq.max_tool_rounds", 4)
RATE_LIMIT_MAX_RETRIES = config_get("groq.rate_limit_max_retries", 3)
RATE_LIMIT_FALLBACK_WAIT_SECONDS = config_get("groq.rate_limit_fallback_wait_seconds", 5)

_WAIT_SECONDS_RE = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)


def has_key():
    return bool(os.environ.get("GROQ_API_KEY"))


def call_groq_once(messages, tools=None, response_format=None, max_tokens=None, tool_choice=None):
    """Confirmed live (multiple back-to-back pipeline runs on the free tier):
    Groq's free TPM limit (8000) is low enough that even a couple of
    sequential incidents can trip it. A 429 here is routine, not exceptional
    - retry with the wait time the API itself tells us to use, rather than
    failing the whole pipeline run over a transient quota blip."""
    if not has_key():
        raise RuntimeError("GROQ_API_KEY not set")

    body = {"model": DEFAULT_MODEL, "messages": messages, "max_tokens": max_tokens or DEFAULT_MAX_TOKENS}
    if tools:
        body["tools"] = tools
    if response_format:
        body["response_format"] = response_format
    if tool_choice is not None:
        # Confirmed live: once the conversation history contains earlier
        # tool-call turns, merely omitting `tools` isn't a strong enough
        # signal - some reasoning models still emit a tool call anyway, and
        # Groq then rejects the request with "Tool choice is none, but model
        # called a tool". Setting tool_choice explicitly actually suppresses it.
        body["tool_choice"] = tool_choice

    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        res = requests.post(
            GROQ_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            json=body,
            timeout=30
        )
        data = res.json()
        if res.status_code == 429 and attempt < RATE_LIMIT_MAX_RETRIES:
            message = data.get("error", {}).get("message", "")
            wait_match = _WAIT_SECONDS_RE.search(message)
            wait_seconds = float(wait_match.group(1)) + 0.5 if wait_match else RATE_LIMIT_FALLBACK_WAIT_SECONDS
            time.sleep(wait_seconds)
            continue
        break

    if res.status_code != 200:
        raise RuntimeError(f"Groq API error: {data.get('error', {}).get('message', res.status_code)}")
    return data


def run_tool_loop(messages, registry: ToolRegistry, max_tokens=None, trace: AgentTrace = None):
    """Runs the standard tool-calling round-trip against `registry`. Every
    tool call the model makes is routed through registry.execute(), which
    times it and records it into `trace` (a fresh AgentTrace is created if
    the caller doesn't supply one) - so the caller always gets back exactly
    what the agent did and how long each step took, not just its final
    answer."""
    if trace is None:
        trace = AgentTrace()
    msgs = list(messages)
    tool_schemas = registry.schemas()

    for round_i in range(MAX_TOOL_ROUNDS):
        data = call_groq_once(msgs, tools=tool_schemas, max_tokens=max_tokens)
        message = data["choices"][0]["message"]
        msgs.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return {"final_message": message, "trace": trace, "rounds": round_i + 1, "messages": msgs}

        for call in tool_calls:
            fn_name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"])
            except Exception:
                args = {}
                registry.execute("__parse_error__", {"raw": call["function"]["arguments"]}, trace=trace)
            else:
                registry.execute(fn_name, args, trace=trace)
            result = trace.calls[-1].result
            msgs.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})

    # hit MAX_TOOL_ROUNDS without a final answer - ask once more with no tools
    # attached so the model is forced to answer from what it already gathered
    final = call_groq_once(msgs, max_tokens=max_tokens, tool_choice="none")
    return {"final_message": final["choices"][0]["message"], "trace": trace, "rounds": MAX_TOOL_ROUNDS,
            "messages": msgs, "forced_final": True}
