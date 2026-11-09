"""The one topic each video is browsed under, chosen by Jev.

One Decisions API request per video: a single choice question over CATEGORIES,
with the title, channel, tags and the first words of the transcript as state.
scripts/highleveltags.py writes the answer into the transcript file's
`category` field, which file_manager.py and the recommender read.

Each category carries a definition rather than just its name, because the
names alone left the model to guess at the borders. "Cooking" was the clear
case: taste tests, mukbangs and restaurant visits were filed there, so the
category was largely people eating. Eating now goes to Other.

Once eating was out (2026-11-08), Cooking's top was still mostly videos about
food that never cook: talks on healthy eating, chef interviews, podcasts, a
comedy sketch set in a kitchen, coffee-machine reviews, food brands' adverts
and a winery's corporate video. "Making food" read as "about food", so the
definition now asks for preparation the viewer can follow, and names where
the rest goes.

YouTube's own categoryId was considered and is not used: its ~15 buckets put
recipes, make-up tutorials and mukbangs alike under People & Blogs or
Howto & Style.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ai_gateway import JEV_URL, http_client

URL = JEV_URL
MODEL = "typesafe/jev-1.13"      # pinned, like video_quality.py

TRANSCRIPT_WORDS = 120

CATEGORIES: dict[str, str] = {
    "Beauty & Fashion": "Make-up, skincare, hair, nails, clothes, outfits, style and fashion hauls.",
    "Health & Fitness": "Workouts, sport training, nutrition and diets, physical and mental "
                        "health, medicine.",
    "Products & Tech": "Gadgets, phones, computers, software, apps, unboxings and reviews of "
                       "products other than food.",
    "Gaming": "Video games: playthroughs, let's plays, game news and reviews, esports, "
              "cooking or other simulation games.",
    "Anime": "Anime and manga: series, characters, reviews, theories.",
    "Movies": "Films and TV series: reviews, summaries, trailers, behind the scenes, "
              "actors.",
    "Reactions & Commentary": "Reacting to or commenting on other videos, internet drama, "
                              "gossip, celebrities and pop culture.",
    "Challenges & Experiments": "Challenges, pranks, dares, 24-hour challenges and "
                                "experiments done for fun, except eating challenges.",
    "Comedy": "Sketches, stand-up, parodies and other videos made mainly to be funny.",
    "Travel": "Trips, destinations, travel guides, living abroad, sightseeing.",
    "Documentaries": "Documentaries and in-depth reports on real people, places, events, "
                     "crime or society.",
    "Cooking": "Someone prepares food or drink on screen and the viewer can follow how: "
               "recipes, cooking and baking techniques, butchery, meal prep, making coffee, "
               "tea, beer or wine at home. Most of the video is the preparation. A recipe "
               "is Cooking however healthy or slimming it is, whether a home cook or a "
               "restaurant's chef makes it, and whatever machine it is made in. NOT a "
               "video that is only about food: eating or tasting it, talks, interviews, "
               "podcasts or documentaries about food, chefs or restaurants, factories "
               "making food, diet advice without a recipe, reviews of kitchen gadgets, "
               "adverts and company videos, or sketches set in a kitchen.",
    "Science": "Science, nature, animals, space, engineering and how things work.",
    "Politics": "Politics, elections, government, political news and opinion.",
    "Finance": "Money, investing, economy, business, entrepreneurship, personal finance.",
    "Cars": "Cars, motorbikes and other vehicles: reviews, driving, repairs, motorsport.",
    "History": "Historical events, periods and people.",
    "Other": "Anything else, including eating rather than making food: taste tests, "
             "trying snacks or sweets, mukbang, eating challenges, restaurant, fast-food and "
             "street-food visits or reviews, 'what I eat in a day', food hauls. Also talks, "
             "interviews and adverts about food, chefs, restaurants, food brands or "
             "wineries; vlogs, family life, music, religion, crafts and DIY.",
}

QUESTIONS = {"category": {
    "type": "choice",
    "criteria": CATEGORIES,
    "instructions": (
        "The state describes a YouTube video: its title, channel, tags and the first words "
        "of its auto-generated transcript. Which one category would a viewer browsing for "
        "this video look under? Judge what the video is mainly about. A video about food "
        "counts as Cooking when most of it shows someone preparing the food so the viewer "
        "could follow, including healthy recipes, a restaurant chef cooking a dish and "
        "recipes made in a machine. Videos of people eating, tasting or reviewing food, "
        "and talks, interviews or adverts about food, go elsewhere: diet advice without a "
        "recipe to Health & Fitness, kitchen gadget reviews to Products & Tech, food "
        "factories and documentaries to Documentaries, sketches to Comedy, the rest to "
        "Other."),
}}


def state(processed: dict) -> dict[str, Any]:
    """What Jev sees of a processed transcript file."""
    words = "".join(t.get("content", "") for t in processed.get("content") or []).split()
    return {"title": processed.get("title", ""),
            "channel": processed.get("creator", ""),
            "tags": (processed.get("tags") or [])[:15],
            "transcript_start": " ".join(words[:TRANSCRIPT_WORDS])}


def client() -> httpx.Client:
    return http_client("video.category", timeout=60)


def classify(http: httpx.Client, processed: dict, attempts: int = 5) -> str:
    """The likeliest category. Retries transient errors like video_quality.ask."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            r = http.post(URL, json={"model": MODEL, "state": state(processed),
                                     "questions": QUESTIONS})
            if r.status_code == 200:
                p = r.json().get("answers", {}).get("category", {}).get("probabilities")
                if p:
                    return max(p, key=p.get)
                last = RuntimeError("Jev left out the category")
            else:
                last = RuntimeError(f"Jev HTTP {r.status_code}: {r.text[:200]}")
                if r.status_code < 500 and r.status_code not in (408, 429):
                    break
        except httpx.HTTPError as e:
            last = e
        time.sleep(2 ** attempt)
    raise last or RuntimeError("Jev did not answer")
