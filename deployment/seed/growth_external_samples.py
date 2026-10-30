"""Build the Growth workflow's sample external data: one fixed record per store city.

The five research stages (weather, reviews, macro and labor, industry news, local
news) read this file instead of calling outside APIs, so a demo run never waits on
a rate limit or a missing key and tells the same story every time. Weather, labor
and industry news start from one real recorded run; reviews and local news are
written to agree with each store's metrics in the sample workbook.

    uv run python deployment/seed/growth_external_samples.py <recorded_session.json>
"""

# ruff: noqa: E501  (sample review text reads better unwrapped)

from __future__ import annotations

import json
import sys
from pathlib import Path

OUTPUT = Path(
    "agents/pro_code/growth_analysis_workflow/src/growth_analysis_workflow/"
    "resources/sample_external_data.json"
)
MAX_WEATHER_DAYS = 6
MAX_INDUSTRY_ARTICLES = 20

# Reviews per store city: Google rating matches the workbook; the themes follow
# each store's operational gaps (order accuracy, wait time, value, stock-outs).
REVIEWS = {
    "Dallas": (
        3.67,
        412,
        [
            (
                "Marcus T.",
                2,
                "1 week ago",
                "Second time this month my order was missing a side. Food itself was good when it all showed up.",
            ),
            (
                "Priya S.",
                4,
                "2 weeks ago",
                "Great flavors and the bowls are huge. Delivery ran a bit late during the storms.",
            ),
            (
                "Jordan K.",
                2,
                "3 weeks ago",
                "Wrong drink and no sauce. Called and they refunded, but it keeps happening.",
            ),
            (
                "Elena R.",
                5,
                "4 weeks ago",
                "Love being able to order from three brands at once. Everything was hot.",
            ),
            (
                "Chris D.",
                3,
                "5 weeks ago",
                "Pricey for what you get compared to the places down the street.",
            ),
        ],
    ),
    "Naperville": (
        4.33,
        288,
        [
            (
                "Amy L.",
                3,
                "1 week ago",
                "Waited almost 40 minutes for pickup. Food was great once it came out.",
            ),
            (
                "Ben W.",
                2,
                "2 weeks ago",
                "They were out of two items I ordered and didn't tell me until I got there.",
            ),
            ("Sofia G.", 5, "3 weeks ago", "Best tacos in the area, fresh and well packed."),
            (
                "Dan P.",
                4,
                "5 weeks ago",
                "Solid food, the app ordering is easy. Missing utensils again though.",
            ),
        ],
    ),
    "Tempe": (
        4.10,
        356,
        [
            (
                "Kayla M.",
                3,
                "1 week ago",
                "Food is good but the wait has gotten long, 35+ minutes on a Tuesday.",
            ),
            ("Ryan H.", 2, "2 weeks ago", "Missing the side salad and the order took forever."),
            ("Ana V.", 4, "3 weeks ago", "Good portions. A little expensive for a student budget."),
            (
                "Luis C.",
                5,
                "4 weeks ago",
                "Chicken sandwich was excellent and still crispy on arrival.",
            ),
        ],
    ),
    "Edina": (
        4.29,
        241,
        [
            (
                "Megan F.",
                3,
                "1 week ago",
                "Ordered the special and it was sold out. Swapped to something else that was fine.",
            ),
            ("Tom B.", 4, "2 weeks ago", "Consistently tasty. Prices crept up a bit this fall."),
            (
                "Grace N.",
                2,
                "3 weeks ago",
                "Missing an entree and had to call. Credit took a few days.",
            ),
            ("Henry O.", 5, "5 weeks ago", "Great family dinner option, kids love the pizza."),
        ],
    ),
    "Houston": (
        4.31,
        397,
        [
            ("Jasmine W.", 3, "1 week ago", "Pickup took 35 minutes even though the app said 15."),
            (
                "Carlos M.",
                4,
                "2 weeks ago",
                "Really good food. Feels a little pricey for weeknight dinner.",
            ),
            ("Brian S.", 2, "3 weeks ago", "Drink was wrong and fries were missing."),
            ("Leah T.", 5, "4 weeks ago", "Everything hot and correct, fast delivery."),
        ],
    ),
    "Kansas City": (
        4.35,
        203,
        [
            ("Nate R.", 3, "1 week ago", "Burger was overcooked and missing the side I paid for."),
            ("Olivia J.", 5, "2 weeks ago", "Fresh, flavorful, and the staff is friendly."),
            ("Sam E.", 3, "4 weeks ago", "Taste is fine, not as good as when it first opened."),
            ("Kim A.", 4, "5 weeks ago", "Good variety, a couple of errors lately with sauces."),
        ],
    ),
    "Columbus": (
        3.85,
        318,
        [
            (
                "Tyler B.",
                2,
                "1 week ago",
                "Half my order was out of stock and the wait was 40 minutes.",
            ),
            ("Hannah L.", 3, "2 weeks ago", "Wrong item again. The food is good when it is right."),
            ("Omar Z.", 4, "3 weeks ago", "Great late-night option near campus."),
            ("Rachel P.", 2, "5 weeks ago", "Long wait and cold fries. Expected better."),
        ],
    ),
    "Cary": (
        4.69,
        176,
        [
            ("Linda K.", 5, "1 week ago", "Delicious and the packaging keeps everything fresh."),
            ("Steve M.", 4, "2 weeks ago", "Great food but on the expensive side for the portion."),
            ("Paula D.", 3, "3 weeks ago", "Missing a side and one item was unavailable."),
            ("Greg H.", 5, "4 weeks ago", "Best salad bowls around, always consistent."),
        ],
    ),
}

# Local market news per store city, fictional but plausible for the period.
LOCAL_NEWS = {
    "Dallas": [
        (
            "Uptown restaurant row adds three fast-casual openings this fall",
            "Dallas Observer",
            "2026-10-08",
        ),
        (
            "Flash flooding closes McKinney Avenue lanes during early October storms",
            "Dallas Morning News",
            "2026-10-02",
        ),
    ],
    "Naperville": [
        (
            "Downtown Naperville parking garage closes for repairs through November",
            "Naperville Sun",
            "2026-10-05",
        ),
    ],
    "Tempe": [
        (
            "ASU fall enrollment hits record, boosting late-night dining demand",
            "Phoenix New Times",
            "2026-09-22",
        ),
        ("New food hall opens on Mill Avenue with 12 vendors", "Eater Phoenix", "2026-10-12"),
    ],
    "Edina": [
        ("Southdale area welcomes two national pizza chains", "Star Tribune", "2026-10-01"),
    ],
    "Houston": [
        (
            "Heights dining scene grows with four new openings on 19th Street",
            "Eater Houston",
            "2026-09-30",
        ),
        (
            "Heavy rain and street flooding disrupt deliveries across inner loop",
            "Houston Chronicle",
            "2026-10-03",
        ),
    ],
    "Kansas City": [
        (
            "Crossroads district road work slows evening traffic through October",
            "Kansas City Star",
            "2026-09-25",
        ),
    ],
    "Columbus": [
        (
            "Short North sees surge of late-night delivery competition near campus",
            "Columbus Dispatch",
            "2026-10-09",
        ),
    ],
    "Cary": [
        (
            "Cary town center redevelopment brings new restaurant tenants",
            "News & Observer",
            "2026-10-14",
        ),
    ],
}

# The recorded run had no FRED key; this fills the gap with a plausible reading.
FRED_RETAIL_SALES = {"value_millions_usd": 101234, "date": "2026-09-01", "error": None}


def _responses(session_file: Path) -> dict[str, object]:
    events = json.loads(session_file.read_text(encoding="utf-8-sig"))["sessionEvents"]
    found: dict[str, object] = {}
    for event in events:
        for part in event["content"].get("parts", []):
            response = part.get("functionResponse")
            if response and response["name"] not in found:
                body = response["response"]
                if isinstance(body.get("result"), str):
                    body = json.loads(body["result"])
                found[response["name"]] = body
    return found


def build(session_file: Path) -> dict[str, object]:
    recorded = _responses(session_file)
    stores = recorded["fetch_top_and_bottom_performing_stores"]["bottom_5_weather_agent_input"]
    city_by_id = {}
    weather = {}
    for store_id, record in recorded["fetch_weather_batch"].items():
        city = next(s["city"] for s in stores if abs(float(s["lat"]) - record["latitude"]) < 0.01)
        city_by_id[store_id] = city
        record = dict(record)
        record["anomalous_daily_records"] = record["anomalous_daily_records"][:MAX_WEATHER_DAYS]
        weather[city] = record

    macro = recorded["fetch_macro_labor_batch"]
    macro["fred_retail_sales"].update(FRED_RETAIL_SALES)

    industry = recorded["fetch_qsr_industry_news_batch"]
    industry["articles"] = industry["articles"][:MAX_INDUSTRY_ARTICLES]
    industry["total_articles_ingested"] = len(industry["articles"])

    reviews = {
        city: {
            "place_id": f"sample-{city.lower().replace(' ', '-')}",
            "display_name": next(s["store_name"] for s in stores if s["city"] == city),
            "rating": rating,
            "user_rating_count": count,
            "recent_reviews": [
                {"author_name": a, "rating": float(r), "relative_time": t, "text": x}
                for a, r, t, x in items
            ],
        }
        for city, (rating, count, items) in REVIEWS.items()
    }
    local_news = {
        city: [
            {"title": title, "source": source, "published": date, "city": city}
            for title, source, date in items
        ]
        for city, items in LOCAL_NEWS.items()
    }
    return {
        "note": "Sample external data for the demo; see deployment/seed/growth_external_samples.py.",
        "weather": weather,
        "reviews": reviews,
        "macro_labor": macro,
        "industry_news": industry,
        "local_news": local_news,
    }


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(Path(sys.argv[1])), indent=1), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)")
