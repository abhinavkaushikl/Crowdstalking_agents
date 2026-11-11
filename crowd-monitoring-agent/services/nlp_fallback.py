"""
Local, non-LLM sentiment fallback for the Social Media Hunter. Used whenever
Groq is unavailable -- no key, or (confirmed live) the free tier's daily
token quota is exhausted. Costs zero API tokens, needs no network call beyond
the same search tools the real hunter uses, and never fails the pipeline.

Uses VADER (Valence Aware Dictionary and sEntiment Reasoner) -- a lexicon/
rule-based analyzer, not a trained model, specifically tuned for short,
informal social-media text (handles slang, emoji-adjacent punctuation like
"!!!", ALL CAPS emphasis, negation) rather than a generic NLP sentiment
model built for formal prose. That's exactly the register of both the
tweet_simulator.py output and real tweets/Reddit posts, which is why it's a
better fit here than a general-purpose classifier would be.

This performs the SAME shaped job as agents.social_media_hunter.hunt_social_media
(search -> judge -> structured verdict) but every decision is a fixed rule
instead of a model's judgment call: queries are built from a fixed template
(not chosen by an LLM), the sentiment score comes straight from VADER's
compound score, and tags come from simple keyword matching. The output has
the exact same shape as the LLM path, plus a "method": "nlp_fallback" marker
so it's never mistaken for an LLM-judged result downstream.
"""
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from tools.search_tools import search_registry

_analyzer = SentimentIntensityAnalyzer()

TAG_KEYWORDS = {
    "protest": ["protest", "march", "rally", "demonstrat", "chant"],
    "celebration": ["celebrat", "festival", "party", "parade", "concert"],
    "emergency": ["emergency", "accident", "collision", "ambulance", "injur", "fire", "police"],
    "unrest": ["riot", "clash", "unrest", "disturbance", "confrontation"],
    "traffic": ["traffic", "congestion", "road closed", "blocked"],
    "nightlife": ["bar", "club", "nightlife", "drinks"],
}


def _build_queries(area, city, streets):
    place = area or city or "the area"
    queries = [f"{place} {city} news today".strip(), f"{place} {city} protest".strip()]
    if streets:
        queries.append(f"{streets[0]} {city} incident".strip())
    return queries[:3]


def _gather_snippets(area, city, streets, trace=None):
    snippets = []
    sources = []
    seen = set()  # queries can legitimately overlap (same real article found two
    # ways); dedupe by (title, url) so it's neither double-counted in the
    # sentiment average nor shown twice in the final sources list.

    def _add(title, url, platform, snippet):
        key = (title, url)
        if key in seen:
            return
        seen.add(key)
        snippets.append(f"{title}. {snippet}")
        sources.append({"title": title, "url": url, "platform": platform})

    for query in _build_queries(area, city, streets):
        web = search_registry.execute("web_search", {"query": query, "num_results": 5}, trace=trace)
        for r in (web.get("results") or []):
            _add(r.get("title", ""), r.get("link"), "web", r.get("snippet", ""))

        reddit = search_registry.execute("reddit_search", {"query": query, "limit": 10}, trace=trace)
        for r in (reddit.get("results") or []):
            _add(r.get("title", ""), r.get("permalink"), "reddit", r.get("snippet", ""))

    return snippets, sources


def _derive_tags(combined_text):
    lowered = combined_text.lower()
    tags = [tag for tag, keywords in TAG_KEYWORDS.items() if any(k in lowered for k in keywords)]
    return tags or ["unclear"]


def _sentiment_label(compound, n_snippets):
    # VADER's lexicon is general-purpose, so even clearly alarming journalistic
    # text ("clashes", "unrest", "disturbance") scores only mildly negative
    # compared to emotionally-charged informal text -- confirmed live against
    # the riot mock scenario (-0.5 never tripped on real wording). -0.3 better
    # separates "alarmed" from "concerned" for this register of text.
    if n_snippets == 0:
        return "unclear"
    if compound <= -0.3:
        return "alarmed"
    if compound <= -0.05:
        return "concerned"
    if compound >= 0.05:
        return "calm"
    return "unclear"


def analyze_with_nlp(context, trace=None):
    flag = context["flag"]
    area = context["area"].get("locality")
    city = context["area"].get("city")
    streets = context["vendors"].get("streets") or []

    snippets, sources = _gather_snippets(area, city, streets, trace=trace)

    if not snippets:
        return {
            "situation_summary": f"Local NLP fallback: no search results found for {area or city or 'this area'} "
                                  f"(detector flagged {flag.get('reason')}, {flag.get('detail', '')}).",
            "sentiment": "unclear",
            "sentiment_score": 0.0,
            "tags": ["unclear"],
            "intent_analysis": "No text available to analyze -- cannot infer intent.",
            "confidence": "low",
            "sources": [],
            "method": "nlp_fallback",
            "tool_trace": trace.to_list() if trace else []
        }

    combined_text = " ".join(snippets)
    scores = [_analyzer.polarity_scores(s)["compound"] for s in snippets]
    avg_compound = sum(scores) / len(scores)

    tags = _derive_tags(combined_text)
    sentiment = _sentiment_label(avg_compound, len(snippets))
    confidence = "medium" if len(snippets) >= 5 else "low"

    top_snippet = max(snippets, key=lambda s: abs(_analyzer.polarity_scores(s)["compound"]))[:200]
    situation_summary = (
        f"Local NLP fallback (VADER, no LLM): analyzed {len(snippets)} search results for "
        f"{area or city or 'this area'}. Avg sentiment {avg_compound:+.2f}. Most notable: \"{top_snippet}\""
    )
    intent_analysis = (
        f"Keyword analysis suggests: {', '.join(tags)}. "
        f"(Rule-based inference, not a model judgment -- treat as a rough signal.)"
    )

    return {
        "situation_summary": situation_summary,
        "sentiment": sentiment,
        "sentiment_score": round(max(-1.0, min(1.0, avg_compound)), 3),
        "tags": tags,
        "intent_analysis": intent_analysis,
        "confidence": confidence,
        "sources": sources[:10],
        "method": "nlp_fallback",
        "tool_trace": trace.to_list() if trace else []
    }
