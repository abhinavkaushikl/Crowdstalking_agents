#!/usr/bin/env python3
"""
Generates realistic-looking SIMULATED tweets about a location/incident -- not
real data, not posted anywhere, purely a stand-in ground truth so the Social
Media Hunter (crowd-monitoring-agent/social_media_hunter.py) has something
genuine to search and analyze when real APIs come back sparse (which is the
normal case for hyper-local, moment-to-moment events -- see DECISIONS.md).

Mirrors live_position_simulator.py's role: that simulates real device
movement as ground truth for the crowd detector; this simulates real-looking
social chatter as ground truth for the sentiment hunter. Both are clearly
synthetic and clearly labeled as such -- never meant to be passed off as, or
mixed with, real user content.

Usage:
    python3 tweet_simulator.py --area "Nordend West" --city "Frankfurt am Main" \\
        --streets "Adickesallee,Wolfsgangstraße" --incident-type crush_inward --count 15

    python3 tweet_simulator.py --area "Altstadt" --city "Frankfurt am Main" \\
        --incident-type panic_outward --count 10 --out /tmp/tweets.json

    # Auto mode: pulls the REAL, complete street list for a zone from the
    # same context_agent.py the Social Media Hunter uses, then scatters
    # tweets randomly across ALL of them (not just 2-3 hand-picked streets):
    python3 tweet_simulator.py --lat 50.12438 --lon 8.67738 --radius-km 2 \\
        --incident-type crush_inward --count 30
"""
import argparse
import datetime
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crowd-monitoring-agent"))

# -- natural-variation building blocks, mixed per incident type -------------
# Tweets are composed from interchangeable fragments (opener + observation +
# location + reaction + closer), not fixed mad-lib templates, so length and
# structure vary too, not just vocabulary. Each incident type gets its own
# (often conflicting) pool -- real crowds produce conflicting reactions, which
# is itself realistic and worth preserving rather than smoothing away.

ALARMED_OPENERS = ["omg", "wait", "uhh", "ok this is scary", "not gonna lie", "everyone is", "people are"]
ALARMED_OBSERVATIONS = [
    "running in every direction near", "pushing past everyone to get away from",
    "screaming near", "sprinting away from", "a huge crowd just scattered near",
    "everyone just started running away from"
]
ALARMED_REACTIONS = [
    "is anyone else seeing this??", "someone please tell me what happened",
    "my heart is racing", "stay away from this area rn", "be careful if you're nearby",
    "hope everyone is ok", "calling my mom rn"
]

CONCERNED_OPENERS = ["hey", "does anyone know", "noticing", "fyi", "heads up", "saw this"]
CONCERNED_OBSERVATIONS = [
    "a lot more police than usual near", "a big crowd building up near",
    "traffic is completely stuck around", "something's going on near",
    "a bunch of people gathering by"
]
CONCERNED_REACTIONS = [
    "anyone know what's happening?", "hope it's nothing serious",
    "kinda weird tbh", "avoid the area if you can", "will update if I find out more"
]

PROTEST_OPENERS = ["we are here", "out here right now", "standing together", "this is happening", "right now"]
PROTEST_OBSERVATIONS = [
    "hundreds marching down", "chanting loudly near", "holding signs outside",
    "blocking traffic on", "gathering peacefully at"
]
PROTEST_REACTIONS = [
    "our voices will be heard", "proud to stand here today", "this is how change happens",
    "more people joining every minute", "peaceful so far"
]

CELEBRATION_OPENERS = ["best night ever", "this is amazing", "so much fun", "can't believe", "wow"]
CELEBRATION_OBSERVATIONS = [
    "the whole street is packed for", "everyone's dancing near", "the crowd at",
    "such good energy outside", "line wrapped around the block at"
]
CELEBRATION_REACTIONS = [
    "best time of my life", "you had to be there", "come through if you're nearby!",
    "wish you were all here", "10/10 would recommend"
]

CONFUSED_OPENERS = ["uh", "lol what", "random but", "does anyone know why", "weird moment"]
CONFUSED_OBSERVATIONS = [
    "a bunch of people just randomly gathered near", "saw a small crowd forming by",
    "some kind of commotion near", "a few people stopped and were looking at something near"
]
CONFUSED_REACTIONS = [
    "probably nothing lol", "no idea what that was about", "anyone know?", "shrug emoji basically",
    "forgot about it 5 min later tbh"
]

INCIDENT_PROFILES = {
    "panic_outward": [
        (0.65, ALARMED_OPENERS, ALARMED_OBSERVATIONS, ALARMED_REACTIONS),
        (0.35, CONCERNED_OPENERS, CONCERNED_OBSERVATIONS, CONCERNED_REACTIONS),
    ],
    "crush_inward": [
        # genuinely ambiguous -- could read as protest or celebration or just
        # concerning density; a real crowd produces all three reactions at once
        (0.40, PROTEST_OPENERS, PROTEST_OBSERVATIONS, PROTEST_REACTIONS),
        (0.30, CELEBRATION_OPENERS, CELEBRATION_OBSERVATIONS, CELEBRATION_REACTIONS),
        (0.30, CONCERNED_OPENERS, CONCERNED_OBSERVATIONS, CONCERNED_REACTIONS),
    ],
    "variance_spike": [
        (0.70, CONFUSED_OPENERS, CONFUSED_OBSERVATIONS, CONFUSED_REACTIONS),
        (0.30, CONCERNED_OPENERS, CONCERNED_OBSERVATIONS, CONCERNED_REACTIONS),
    ],
}
DEFAULT_PROFILE = [
    (0.5, CONFUSED_OPENERS, CONFUSED_OBSERVATIONS, CONFUSED_REACTIONS),
    (0.5, CONCERNED_OPENERS, CONCERNED_OBSERVATIONS, CONCERNED_REACTIONS),
]

HASHTAG_TEMPLATES = ["#{city}", "#{area}", "#breaking", "#whathappening", "#stayaware"]

FIRST_NAMES = ["alex", "sam", "jordan", "max", "mia", "finn", "lea", "nico", "tom", "ana",
               "ben", "ella", "jan", "zoe", "kai", "lina", "theo", "eva", "paul", "mara"]


def _pick_profile(incident_type):
    return INCIDENT_PROFILES.get(incident_type, DEFAULT_PROFILE)


def _weighted_bucket(profile):
    weights = [p[0] for p in profile]
    return random.choices(profile, weights=weights, k=1)[0]


def _location_mention(area, city, streets):
    choices = []
    if streets:
        choices.append(random.choice(streets))
    if area:
        choices.append(area)
    if city:
        choices.append(f"{area}, {city}" if area else city)
    if not choices:
        choices = ["downtown"]
    return random.choice(choices)


def _casual_case(text):
    # real tweets are overwhelmingly lowercase/casual; occasionally Proper Case
    if random.random() < 0.15:
        return text
    return text.lower()


def _maybe_hashtags(area, city):
    if random.random() < 0.4:
        return ""
    tags = random.sample(HASHTAG_TEMPLATES, k=random.randint(1, 2))
    rendered = [t.format(city=(city or "").replace(" ", ""), area=(area or "").replace(" ", "")) for t in tags]
    return " " + " ".join(rendered)


def _maybe_punctuation_flourish(text):
    r = random.random()
    if r < 0.15:
        return text + "..."
    if r < 0.3:
        return text + "!!"
    if r < 0.4:
        return text + "."
    return text


def generate_handle():
    name = random.choice(FIRST_NAMES)
    suffix = random.choice(["", str(random.randint(1, 99)), str(random.randint(1980, 2010)), "_", "xo", "official"])
    return f"@{name}{suffix}"


def generate_tweet(area, city, streets, incident_type, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    profile = _pick_profile(incident_type)
    _, openers, observations, reactions = _weighted_bucket(profile)

    location = _location_mention(area, city, streets)
    parts = [random.choice(openers), random.choice(observations), location]
    if random.random() < 0.8:
        parts.append(random.choice(reactions))

    text = " ".join(parts)
    text = _casual_case(text)
    text = _maybe_punctuation_flourish(text)
    text += _maybe_hashtags(area, city)

    minutes_ago = random.randint(0, 45)
    timestamp = now - datetime.timedelta(minutes=minutes_ago)

    # small-tail engagement distribution: most tweets barely seen, a few take off
    likes = max(0, int(random.paretovariate(1.5) * 2))
    retweets = max(0, int(likes * random.uniform(0.05, 0.3)))

    return {
        "id": f"sim-{random.randint(10**9, 10**10 - 1)}",
        "handle": generate_handle(),
        "text": text,
        "timestamp": timestamp.isoformat(),
        "likes": likes,
        "retweets": retweets,
        "simulated": True
    }


def generate_tweets(area, city, streets, incident_type, count):
    now = datetime.datetime.now(datetime.timezone.utc)
    tweets = [generate_tweet(area, city, streets, incident_type, now=now) for _ in range(count)]
    tweets.sort(key=lambda t: t["timestamp"], reverse=True)
    return tweets


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", default="", help="Locality/area name, e.g. 'Nordend West' (ignored if --lat/--lon given)")
    ap.add_argument("--city", default="", help="City name, e.g. 'Frankfurt am Main' (ignored if --lat/--lon given)")
    ap.add_argument("--streets", default="", help="Comma-separated real street names (ignored if --lat/--lon given)")
    ap.add_argument("--lat", type=float, default=None, help="Auto mode: fetch the REAL area name + ALL real streets in the zone")
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--radius-km", type=float, default=1.5, help="Zone radius for auto mode (default 1.5km)")
    ap.add_argument("--incident-type", default="crush_inward",
                     choices=list(INCIDENT_PROFILES.keys()) + ["unknown"],
                     help="Shapes the mix of reactions generated (matches crowd_anomaly_agent.py's flag reasons)")
    ap.add_argument("--count", type=int, default=15)
    ap.add_argument("--out", default=None, help="Write JSON here instead of stdout")
    ap.add_argument("--seed", type=int, default=None, help="Random seed, for reproducible demo runs")
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    area, city = args.area, args.city
    if args.lat is not None and args.lon is not None:
        # Auto mode: reuse the EXACT same lookup the Social Media Hunter uses
        # (context_agent.py), so tweets scatter across every real street in
        # the zone instead of 2-3 hand-picked ones.
        import context_agent as ca
        import shapely.geometry as geom

        geo = ca.reverse_geocode(args.lat, args.lon)
        area = geo.get("locality") or area
        city = geo.get("city") or city

        # get_nearby_vendors_and_streets caps streets at 30 (sized for the
        # Hunter's LLM context) -- go one level lower for the FULL list, so
        # tweets can scatter across every real street in the zone, not just 30.
        region_name, region = ca.find_region_for_point(args.lat, args.lon)
        if region:
            index_path = os.path.join(ca.OSM_DIR, region["index"])
            points = ca.circle_polygon(args.lat, args.lon, args.radius_km)
            polygon = geom.Polygon([(lng, lt) for lt, lng in points])
            streets_dict, _places = ca.osm_extract.query_index(index_path, polygon, ca.osm_extract.FOOD_AMENITIES)
            streets = sorted(streets_dict.keys())
        else:
            streets = []
        print(f"Auto mode: {area}, {city} -- {len(streets)} real streets found in {args.radius_km}km zone (using ALL of them)", file=sys.stderr)
    else:
        streets = [s.strip() for s in args.streets.split(",") if s.strip()]

    tweets = generate_tweets(area, city, streets, args.incident_type, args.count)

    output = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "simulated": True,
        "note": "SIMULATED DATA -- not real tweets, not posted anywhere, generated for demo/testing only",
        "area": area, "city": city, "incident_type": args.incident_type,
        "streets_used": streets,
        "tweets": tweets
    }

    text = json.dumps(output, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"Wrote {len(tweets)} simulated tweets to {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
