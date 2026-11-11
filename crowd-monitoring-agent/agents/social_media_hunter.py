"""
Stage 2 -- "Social Media Hunter". Given the real streets + area name Stage 1
already gathered for the affected zone, hunt for what's actually being said
about it right now (Google first, then Reddit), and have the LLM judge the
result into a structured sentiment verdict: a numeric score, descriptive
tags, and a read on the crowd's apparent intent -- not just a vague label.

Every failure mode (no GROQ_API_KEY, bad JSON, HTTP errors) must degrade to a
typed fallback and never raise -- poller.py's whole pipeline depends on this
never crashing the process over a missing/expired key.
"""
import json

from services import groq_client as groq
from services.nlp_fallback import analyze_with_nlp
from tools import search_registry
from tools.registry import AgentTrace

FALLBACK = {
    "situation_summary": "Social Media Hunter unavailable (no GROQ_API_KEY configured).",
    "sentiment": "unclear",
    "sentiment_score": 0,
    "tags": [],
    "intent_analysis": "Unknown -- no analysis run.",
    "confidence": "low",
    "sources": []
}

SYSTEM_PROMPT = """You are the "Social Media Hunter" for a city crowd-monitoring system. \
A statistical anomaly detector (not you) has already flagged unusual, coherent crowd \
movement across a real zone -- you are given the REAL street names and area name inside \
that zone (from offline map data, not guessed). Your job: hunt for what's actually being \
said or reported about this specific place right now, and judge the crowd's sentiment and \
apparent intent.

Tool order: ALWAYS call web_search (Google) first -- it is your primary source. Only call \
reddit_search afterward if you want a second, more informal read. Build your queries using \
the REAL street names and area name you were given (e.g. "<street name> <city> protest" or \
"<area name> <city> news today"), not the raw detector jargon (never search literally for \
"crush_inward" or "panic_outward").

Call tools as needed, then stop once you have enough to judge. Be honest about uncertainty: \
if searches return nothing relevant, say so plainly and keep confidence low -- never invent a \
plausible-sounding explanation or source."""

FINAL_JSON_INSTRUCTION = (
    'Based on everything above, respond with ONLY a JSON object, no other text, '
    'with exactly these keys: '
    'situation_summary (1-3 sentences, what you think is actually happening), '
    'sentiment (one of: "calm", "concerned", "alarmed", "unclear"), '
    'sentiment_score (a number from -1.0 to 1.0: -1.0 = very negative/alarming, 0 = neutral, '
    '1.0 = very positive/calm), '
    'tags (array of short lowercase strings describing the apparent situation type, e.g. '
    '"protest", "celebration", "nightlife", "concert", "sports-event", "traffic", "emergency", '
    '"routine", "unclear" -- use as many as genuinely apply, or ["unclear"] if nothing fits), '
    'intent_analysis (1-2 sentences on what the crowd actually appears to be doing/trying to do), '
    'confidence ("low", "medium", or "high"), '
    'sources (array of {title, url, platform} drawn from your actual search results -- empty array if none).'
)


def _build_user_message(context):
    flag = context["flag"]
    area = context["area"]
    vendors = context["vendors"]
    return json.dumps({
        "detected_anomaly": {
            "reason": flag.get("reason"), "detail": flag.get("detail"),
            "device_count": flag.get("device_count"), "mean_speed_kmh": flag.get("mean_speed_kmh")
        },
        "area": {"locality": area.get("locality"), "city": area.get("city")},
        "real_streets_in_zone": (vendors.get("streets") or [])[:15],
        "nearby_landmarks_sample": [v["name"] for v in (vendors.get("vendors") or [])[:5]]
    })


MAX_FINAL_JSON_RETRIES = 2


def _get_final_json(msgs, trace):
    """Asks for the final JSON verdict with tool_choice="none". Confirmed
    live: some reasoning models still emit a tool call anyway even with that
    set, and Groq then rejects the whole response with "Tool choice is none,
    but model called a tool" - not something a request parameter can fully
    prevent, since it's the model's own non-compliant output. Rather than
    fighting that, let it make the one more tool call it wants, feed the
    result back, then ask again."""
    for round_i in range(MAX_FINAL_JSON_RETRIES + 1):
        final_messages = msgs + [{"role": "user", "content": FINAL_JSON_INSTRUCTION}]
        try:
            data = groq.call_groq_once(final_messages, response_format={"type": "json_object"},
                                        max_tokens=1000, tool_choice="none")
            return json.loads(data["choices"][0]["message"]["content"])
        except RuntimeError as e:
            if "Tool choice is none, but model called a tool" not in str(e) or round_i == MAX_FINAL_JSON_RETRIES:
                raise
            data = groq.call_groq_once(final_messages, tools=search_registry.schemas(), max_tokens=1000)
            message = data["choices"][0]["message"]
            msgs = msgs + [{"role": "user", "content": FINAL_JSON_INSTRUCTION}, message]
            for call in message.get("tool_calls") or []:
                try:
                    args = json.loads(call["function"]["arguments"])
                except Exception:
                    args = {}
                search_registry.execute(call["function"]["name"], args, trace=trace)
                msgs.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(trace.calls[-1].result)})
    raise RuntimeError("could not obtain a final JSON verdict after retries")


def hunt_social_media(context):
    if not groq.has_key():
        result = analyze_with_nlp(context, trace=AgentTrace())
        result["note"] = "GROQ_API_KEY not set -- used local NLP fallback (VADER) instead of LLM judgment."
        return result

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(context)}
        ]

        loop_result = groq.run_tool_loop(messages, search_registry, max_tokens=1500)
        parsed = _get_final_json(loop_result["messages"], loop_result["trace"])

        try:
            score = max(-1.0, min(1.0, float(parsed.get("sentiment_score", 0))))
        except (TypeError, ValueError):
            score = 0.0

        return {
            "situation_summary": parsed.get("situation_summary") or FALLBACK["situation_summary"],
            "sentiment": parsed.get("sentiment") or "unclear",
            "sentiment_score": score,
            "tags": parsed.get("tags") if isinstance(parsed.get("tags"), list) else [],
            "intent_analysis": parsed.get("intent_analysis") or FALLBACK["intent_analysis"],
            "confidence": parsed.get("confidence") or "low",
            "sources": parsed.get("sources") if isinstance(parsed.get("sources"), list) else [],
            "tool_trace": loop_result["trace"].to_list()
        }
    except Exception as e:
        # LLM path failed (rate limit, bad key, HTTP error, etc.) -- fall back
        # to the local NLP analyzer rather than just reporting the failure, so
        # the pipeline still produces a real (if less nuanced) signal.
        result = analyze_with_nlp(context, trace=AgentTrace())
        result["note"] = f"LLM unavailable ({e}) -- used local NLP fallback (VADER) instead."
        result["error"] = str(e)
        return result
