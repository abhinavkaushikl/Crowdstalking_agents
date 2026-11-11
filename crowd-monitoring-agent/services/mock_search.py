"""
Synthetic stand-in for google_search.web_search / reddit_search.search_reddit,
used automatically when the real provider's keys aren't configured (so the
Social Media Hunter's actual Groq reasoning can still be exercised end-to-end
against realistic-looking content instead of an empty result set).

Every result this returns carries "simulated": True so it can never be
mistaken for a real search result downstream or in logs/output.

set_scenario() lets a test deliberately choose what's "actually happening"
(riot, celebration, ...) so the real sentiment analyzer's output can be
checked against a known ground truth, the same principle used for the
crowd-anomaly detector's case studies in ../cases/.
"""
import random

SCENARIOS = {
    "riot": {
        "expected_sentiment": "alarmed",
        "expected_negative": True,
        "web": [
            ("Clashes reported near {area}, police on scene",
             "Local news is reporting a large crowd confrontation near {area} this evening. "
             "Several witnesses describe people running and shouting; authorities have been dispatched."),
            ("Unrest breaks out in {area} district",
             "Video circulating online shows a tense standoff and a crowd scattering near {area}. "
             "Local businesses reportedly closed early as a precaution."),
            ("BREAKING: disturbance near {area}, avoid the area",
             "City officials are advising residents to avoid {area} following reports of a crowd "
             "disturbance. No official statement yet on the cause."),
        ],
        "reddit": [
            ("Anyone know what's happening near {area} right now??",
             "Heard shouting and saw a huge crowd just start running near {area}. Something's going on, stay safe out there."),
            ("Unrest near {area} tonight",
             "Live updates: seems like things are getting tense near {area}. Multiple people posting about police showing up."),
        ],
    },
    "celebration": {
        "expected_sentiment": "calm",
        "expected_negative": False,
        "web": [
            ("{area} packed for street festival celebrations",
             "Crowds gathered in {area} tonight for what locals describe as a spontaneous street celebration, "
             "with music and cheering reported throughout the evening."),
            ("Big win sparks celebrations near {area}",
             "Fans flooded the streets near {area} celebrating a major local sports victory. Police report no incidents, "
             "just a festive, high-energy crowd."),
        ],
        "reddit": [
            ("{area} is LIT tonight lol",
             "Whole street is out celebrating near {area}, great vibes, everyone's just having a good time."),
            ("Street party near {area}??",
             "Walked through {area} and it's basically a party out there, people singing and dancing, nothing bad going on."),
        ],
    },
    "concert_dispersal": {
        "expected_sentiment": "calm",
        "expected_negative": False,
        "web": [
            ("Concert lets out near {area}, heavy foot traffic expected",
             "A sold-out show just ended near {area}; expect large but orderly crowds heading toward transit "
             "over the next hour. No incidents reported."),
        ],
        "reddit": [
            ("Just left the show near {area}, so many people leaving at once",
             "Crowd control was fine honestly, just a lot of people all walking out together toward the station near {area}."),
        ],
    },
    "mundane": {
        "expected_sentiment": "calm",
        "expected_negative": False,
        "web": [
            ("Evening commute reported normal near {area}",
             "No unusual activity reported near {area} this evening; typical weekday foot and vehicle traffic."),
        ],
        "reddit": [
            ("Nothing going on near {area} that I can see",
             "Walked through {area} earlier, looked completely normal, not sure why anyone would be asking."),
        ],
    },
    "accident": {
        "expected_sentiment": "concerned",
        "expected_negative": True,
        "web": [
            ("Traffic incident reported near {area}",
             "Emergency services responded to a reported traffic collision near {area}. Minor delays expected; "
             "no word yet on injuries."),
        ],
        "reddit": [
            ("Fender bender near {area}?",
             "Saw an ambulance and some flashing lights near {area}, looked like a car accident, nothing crazy."),
        ],
    },
}

_current_scenario = None


def set_scenario(name):
    """name must be a key in SCENARIOS, or None/"random" to pick one at random."""
    global _current_scenario
    if name in (None, "random"):
        name = random.choice(list(SCENARIOS))
    if name not in SCENARIOS:
        raise ValueError(f"Unknown mock scenario '{name}', choose from {list(SCENARIOS)}")
    _current_scenario = name
    return name


def current_scenario():
    return _current_scenario


def _area_from_query(query):
    # crude heuristic: strip common suffix words the real hunter appends
    for suffix in [" protest", " news today", " news", " today", " unrest", " celebration"]:
        if query.lower().endswith(suffix):
            return query[: -len(suffix)]
    return query


def web_search(query, num_results=None):
    if _current_scenario is None:
        set_scenario("random")
    area = _area_from_query(query)
    bank = SCENARIOS[_current_scenario]["web"]
    n = min(int(num_results or 5), len(bank))
    picked = random.sample(bank, n) if n < len(bank) else list(bank)
    results = [{"title": t.format(area=area), "link": f"https://example-news.test/{i}",
                "snippet": s.format(area=area)} for i, (t, s) in enumerate(picked)]
    return {"result_count": len(results), "results": results, "simulated": True,
            "simulated_scenario": _current_scenario}


def search_reddit(query, limit=None):
    if _current_scenario is None:
        set_scenario("random")
    area = _area_from_query(query)
    bank = SCENARIOS[_current_scenario]["reddit"]
    n = min(int(limit or 10), len(bank))
    picked = random.sample(bank, n) if n < len(bank) else list(bank)
    results = [{"title": t.format(area=area), "snippet": s.format(area=area),
                "subreddit": "r/frankfurt", "score": random.randint(5, 400),
                "permalink": f"https://reddit.com/r/frankfurt/test/{i}"} for i, (t, s) in enumerate(picked)]
    return {"result_count": len(results), "results": results, "simulated": True,
            "simulated_scenario": _current_scenario}
