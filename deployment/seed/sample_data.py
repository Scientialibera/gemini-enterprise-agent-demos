"""Synthetic BigQuery source data, so the agents can be deployed and demonstrated without real data.

Creates the source tables the agents read, in the target project:

    ops_analytics      order_compliance_daily, kitchen_compliance_items
                       (Kitchen Sequencer's curated tables are built from these)
    recipe_products    product recipe tables read by Recipe QA
    recipe_legacy      legacy recipe tables read by Recipe QA

Every value is made up: the kitchens, people, recipes and numbers belong to no real
company. Rows are generated with a fixed seed, and dates are relative to the day
the data is loaded, so "this week" and "the last 7 days" always have data. Tables
are replaced on each run.
"""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from config.environment import env_bool

SEED_ENV = "DEV_SEED_SAMPLE_DATA"
LOCATION_ENV = "SAMPLE_DATA_LOCATION"
DEFAULT_LOCATION = "US"
KITCHEN_DATASET = "ops_analytics"
RECIPE_PRODUCT_DATASET = "recipe_products"
RECIPE_LEGACY_DATASET = "recipe_legacy"
SEED = 20261026
EASTERN = ZoneInfo("America/New_York")

Row = dict[str, object]


@dataclass(frozen=True, slots=True)
class Table:
    dataset: str
    name: str
    schema: tuple[tuple[str, str, str], ...]  # name, type, mode
    rows: Callable[[dt.date], Iterator[Row]]
    partition_field: str | None = None


def sample_data_enabled() -> bool:
    return env_bool(SEED_ENV, False)


# ---------------------------------------------------------------- kitchens

KITCHENS = (
    # kitchen_id, code, name, city, state, regional manager, area director, population
    (
        "k-001",
        "TX-SCO",
        "South Congress Kitchen",
        "Austin",
        "TX",
        "Maya Torres",
        "Owen Blake",
        "Urban",
    ),
    (
        "k-002",
        "TX-RRK",
        "Round Rock Kitchen",
        "Round Rock",
        "TX",
        "Maya Torres",
        "Owen Blake",
        "Suburban",
    ),
    ("k-003", "TX-UPT", "Uptown Kitchen", "Dallas", "TX", "Maya Torres", "Owen Blake", "Urban"),
    ("k-004", "TX-PLN", "Plano Kitchen", "Plano", "TX", "Jordan Hale", "Owen Blake", "Suburban"),
    ("k-005", "TX-HTS", "Heights Kitchen", "Houston", "TX", "Jordan Hale", "Owen Blake", "Urban"),
    ("k-006", "CO-HLD", "Highlands Kitchen", "Denver", "CO", "Priya Nair", "Owen Blake", "Urban"),
    (
        "k-007",
        "CO-LTN",
        "Littleton Kitchen",
        "Littleton",
        "CO",
        "Priya Nair",
        "Owen Blake",
        "Suburban",
    ),
    (
        "k-008",
        "IL-WKP",
        "Wicker Park Kitchen",
        "Chicago",
        "IL",
        "Sam Okafor",
        "Lena Fischer",
        "Urban",
    ),
    (
        "k-009",
        "IL-NPV",
        "Naperville Kitchen",
        "Naperville",
        "IL",
        "Sam Okafor",
        "Lena Fischer",
        "Suburban",
    ),
    (
        "k-010",
        "MN-NLP",
        "North Loop Kitchen",
        "Minneapolis",
        "MN",
        "Ellie Park",
        "Lena Fischer",
        "Urban",
    ),
    ("k-011", "MN-EDN", "Edina Kitchen", "Edina", "MN", "Ellie Park", "Lena Fischer", "Suburban"),
    ("k-012", "GA-MTN", "Midtown Kitchen", "Atlanta", "GA", "Chris Dunn", "Lena Fischer", "Urban"),
    (
        "k-013",
        "TX-PRL",
        "Pearl District Kitchen",
        "San Antonio",
        "TX",
        "Jordan Hale",
        "Owen Blake",
        "Urban",
    ),
    ("k-014", "TX-FRS", "Frisco Kitchen", "Frisco", "TX", "Maya Torres", "Owen Blake", "Suburban"),
    ("k-015", "CO-BLD", "Boulder Kitchen", "Boulder", "CO", "Priya Nair", "Owen Blake", "Suburban"),
    (
        "k-016",
        "IL-EVN",
        "Evanston Kitchen",
        "Evanston",
        "IL",
        "Sam Okafor",
        "Lena Fischer",
        "Suburban",
    ),
    (
        "k-017",
        "GA-DEC",
        "Decatur Kitchen",
        "Decatur",
        "GA",
        "Chris Dunn",
        "Lena Fischer",
        "Suburban",
    ),
    (
        "k-018",
        "GA-ALP",
        "Alpharetta Kitchen",
        "Alpharetta",
        "GA",
        "Chris Dunn",
        "Lena Fischer",
        "Suburban",
    ),
    ("k-019", "AZ-TMP", "Tempe Kitchen", "Tempe", "AZ", "Rosa Medina", "Owen Blake", "Urban"),
    (
        "k-020",
        "AZ-SCT",
        "Scottsdale Kitchen",
        "Scottsdale",
        "AZ",
        "Rosa Medina",
        "Owen Blake",
        "Suburban",
    ),
)
# How much worse each kitchen gets (last complete week, the week before), so the
# ranking has a failing kitchen, a slipping one and a week-over-week story to tell.
RECENT_RISK_MULTIPLIER = {"k-003": (3.6, 2.4), "k-009": (4.5, 2.4), "k-006": (2.2, 1.4)}
COMPLIANCE_DRIVERS = ("Force Complete", "Short Cook", "Hot Hold", "Missing Pouch", "Scan Miss")
DELAY_DRIVERS = ("Late Driver", "Kitchen Backlog", "Ticket Spike", "Equipment Down")
MENU_ITEMS = (
    ("Chicken Tikka Bowl", "Spice Route", "Hot"),
    ("Smash Burger", "Griddle House", "Hot"),
    ("Crispy Chicken Tenders", "Griddle House", "Fry"),
    ("Mozzarella Sticks", "Slice Shop", "Fry"),
    ("Margherita Pizza", "Slice Shop", "Hot"),
    ("Pad Thai", "Noodle Lab", "Hot"),
    ("Salmon Poke", "Poke Spot", "Cold"),
    ("Caesar Salad", "Greens Co", "Cold"),
    ("Truffle Fries", "Griddle House", "Fry"),
)
ORDER_DAYS = 98
ITEM_DAYS = 35
ORDERS_PER_DAY = 26

ORDER_SCHEMA = (
    ("order_id", "STRING", "REQUIRED"),
    ("kitchen_id", "STRING", "REQUIRED"),
    ("service_date_et", "DATE", "REQUIRED"),
    ("is_official_compliance_eligible", "BOOLEAN", "NULLABLE"),
    ("num_items", "INTEGER", "NULLABLE"),
    ("num_cookable_items", "INTEGER", "NULLABLE"),
    ("num_items_short_cooked", "INTEGER", "NULLABLE"),
    ("has_force_complete", "INTEGER", "NULLABLE"),
    ("has_premature_force_complete", "INTEGER", "NULLABLE"),
    ("has_critical_force_complete", "INTEGER", "NULLABLE"),
    ("has_short_cook", "INTEGER", "NULLABLE"),
    ("has_hot_hold_violation", "INTEGER", "NULLABLE"),
    ("has_surprise_pouch", "INTEGER", "NULLABLE"),
    ("has_missing_pouch", "INTEGER", "NULLABLE"),
    ("raw_was_fully_scanned", "INTEGER", "NULLABLE"),
    ("has_quality_compliance_issue", "INTEGER", "NULLABLE"),
    ("has_fq_complaint", "INTEGER", "NULLABLE"),
    ("has_4_wall_accuracy_issue", "INTEGER", "NULLABLE"),
    ("primary_compliance_driver", "STRING", "NULLABLE"),
    ("primary_delay_driver", "STRING", "NULLABLE"),
)

ITEM_SCHEMA = (
    ("service_date_et", "DATE", "REQUIRED"),
    ("kitchen_id", "STRING", "REQUIRED"),
    ("kitchen_code", "STRING", "NULLABLE"),
    ("kitchen_name", "STRING", "NULLABLE"),
    ("kitchen_type", "STRING", "NULLABLE"),
    ("kitchen_class", "STRING", "NULLABLE"),
    ("area_director", "STRING", "NULLABLE"),
    ("regional_manager", "STRING", "NULLABLE"),
    ("city", "STRING", "NULLABLE"),
    ("state_code", "STRING", "NULLABLE"),
    ("population_type", "STRING", "NULLABLE"),
    ("is_currently_mature", "BOOLEAN", "NULLABLE"),
    ("order_number", "STRING", "NULLABLE"),
    ("menu_item_name", "STRING", "NULLABLE"),
    ("restaurant_brand_name", "STRING", "NULLABLE"),
    ("station_code", "STRING", "NULLABLE"),
    ("station_type", "STRING", "NULLABLE"),
    ("is_peak_hour", "BOOLEAN", "NULLABLE"),
    ("force_complete_severity_tier", "STRING", "NULLABLE"),
    ("is_scored_short_cook", "INTEGER", "NULLABLE"),
    ("has_quality_compliance_issue", "INTEGER", "NULLABLE"),
    ("has_timing_compliance_issue", "INTEGER", "NULLABLE"),
    ("has_scanned", "INTEGER", "NULLABLE"),
    ("kitchen_on_time_issue", "BOOLEAN", "NULLABLE"),
    ("is_kitchen_fault", "BOOLEAN", "NULLABLE"),
)


def _risk(kitchen_id: str, day: dt.date, today: dt.date) -> float:
    """Baseline issue probability, rising for the slipping kitchens over the last two weeks."""
    base = 0.006 + (int(kitchen_id[-3:]) % 4) * 0.0035
    last_week_start = today - dt.timedelta(days=today.weekday() + 7)
    last_week, prior_week = RECENT_RISK_MULTIPLIER.get(kitchen_id, (1.0, 1.0))
    if day >= last_week_start:
        return base * last_week
    if day >= last_week_start - dt.timedelta(days=7):
        return base * prior_week
    return base


def _orders(today: dt.date) -> Iterator[Row]:
    rng = random.Random(SEED)
    for offset in range(ORDER_DAYS, 0, -1):
        day = today - dt.timedelta(days=offset)
        for kitchen in KITCHENS:
            kitchen_id = kitchen[0]
            risk = _risk(kitchen_id, day, today)
            for n in range(ORDERS_PER_DAY + rng.randint(-6, 6)):
                items = rng.randint(1, 4)
                cookable = rng.randint(1, items)
                force = int(rng.random() < risk * 2)
                short = int(rng.random() < risk * 1.3)
                hot_hold = int(rng.random() < risk * 0.6)
                missing = int(rng.random() < risk * 0.4)
                scanned = int(rng.random() > risk * 1.2)
                drivers = [
                    name
                    for name, hit in zip(
                        COMPLIANCE_DRIVERS,
                        (force, short, hot_hold, missing, 1 - scanned),
                        strict=True,
                    )
                    if hit
                ]
                yield {
                    "order_id": f"{kitchen_id}-{day:%Y%m%d}-{n:03d}",
                    "kitchen_id": kitchen_id,
                    "service_date_et": day.isoformat(),
                    "is_official_compliance_eligible": rng.random() > 0.03,
                    "num_items": items,
                    "num_cookable_items": cookable,
                    "num_items_short_cooked": min(cookable, short * rng.randint(1, cookable)),
                    "has_force_complete": force,
                    "has_premature_force_complete": force * int(rng.random() < 0.5),
                    "has_critical_force_complete": force * int(rng.random() < 0.2),
                    "has_short_cook": short,
                    "has_hot_hold_violation": hot_hold,
                    "has_surprise_pouch": int(rng.random() < risk * 0.3),
                    "has_missing_pouch": missing,
                    "raw_was_fully_scanned": scanned,
                    "has_quality_compliance_issue": int(short or hot_hold),
                    "has_fq_complaint": int(rng.random() < risk * 0.5),
                    "has_4_wall_accuracy_issue": int(rng.random() < risk * 0.3),
                    "primary_compliance_driver": drivers[0] if drivers else None,
                    "primary_delay_driver": (
                        rng.choice(DELAY_DRIVERS) if rng.random() < risk * 3 else None
                    ),
                }


def _items(today: dt.date) -> Iterator[Row]:
    rng = random.Random(SEED + 1)
    for offset in range(ITEM_DAYS, 0, -1):
        day = today - dt.timedelta(days=offset)
        for kitchen_id, code, name, city, state, manager, director, population in KITCHENS:
            risk = _risk(kitchen_id, day, today)
            for n in range(ORDERS_PER_DAY):
                for _ in range(rng.randint(1, 3)):
                    item, brand, station = rng.choice(MENU_ITEMS)
                    # Fry stations carry most of the short cooks, as they tend to.
                    short_risk = risk * (2.2 if station == "Fry" else 0.6)
                    force = rng.random() < risk * 2
                    timing = rng.random() < risk
                    yield {
                        "service_date_et": day.isoformat(),
                        "kitchen_id": kitchen_id,
                        "kitchen_code": code,
                        "kitchen_name": name,
                        "kitchen_type": "Delivery kitchen",
                        "kitchen_class": "Standard",
                        "area_director": director,
                        "regional_manager": manager,
                        "city": city,
                        "state_code": state,
                        "population_type": population,
                        "is_currently_mature": True,
                        "order_number": f"{code}-{day:%m%d}-{n:03d}",
                        "menu_item_name": item,
                        "restaurant_brand_name": brand,
                        "station_code": f"{station.upper()}-{rng.randint(1, 3)}",
                        "station_type": station,
                        "is_peak_hour": rng.random() < 0.4,
                        "force_complete_severity_tier": (
                            rng.choice(("Low", "Medium", "Critical")) if force else None
                        ),
                        "is_scored_short_cook": int(rng.random() < short_risk),
                        "has_quality_compliance_issue": int(rng.random() < risk),
                        "has_timing_compliance_issue": int(timing),
                        "has_scanned": int(rng.random() > risk * 1.2),
                        "kitchen_on_time_issue": timing,
                        "is_kitchen_fault": timing and rng.random() < 0.6,
                    }


# ---------------------------------------------------------------- recipes

# sku, recipe_id, title, subtitle, servings, active minutes, total minutes.
RECIPES = (
    ("810020001", 86001, "Seared Salmon", "with Lemon-Dill Rice & Green Beans", 2, 25, 35),
    ("810020002", 86002, "Chicken Tikka Masala", "with Basmati Rice & Warm Naan", 2, 30, 40),
    # Timing: active time is longer than total time, and the gochujang is never used.
    ("810020003", 86003, "Beef Bulgogi Bowls", "with Kimchi & Sesame Cucumbers", 2, 40, 30),
    ("810020004", 86004, "Creamy Mushroom Risotto", "with Parmesan & Thyme", 2, 35, 40),
    # Scallions are listed but never used; cilantro is used but not listed.
    ("810020005", 86005, "Chipotle Shrimp Tacos", "with Lime Crema & Cabbage Slaw", 2, 20, 25),
    # A step calls for cilantro, which is not in the ingredient list.
    ("810020006", 86006, "Pork Pad Thai", "with Peanuts & Lime", 2, 25, 30),
    # The bake step gives no oven temperature.
    ("810020007", 86007, "Spinach & Ricotta Lasagna", "with Roasted Zucchini", 4, 30, 60),
    ("810020008", 86008, "Miso-Glazed Cod", "with Ginger Bok Choy & Jasmine Rice", 2, 20, 25),
    # "The same skillet" is used before any skillet has been introduced.
    (
        "810020009",
        86009,
        "Sheet Pan Chicken Fajitas",
        "with Peppers & Charred Tortillas",
        2,
        20,
        35,
    ),
    ("810020010", 86010, "Pesto Gnocchi", "with Blistered Tomatoes & Mozzarella", 2, 20, 25),
    # Uses "the remaining" yogurt sauce, though all of it went into an earlier step.
    ("810020011", 86011, "Harissa Chickpea Bowls", "with Herbed Yogurt & Farro", 2, 25, 35),
    ("810020012", 86012, "Garlic Butter Steak", "with Smashed Potatoes & Arugula", 2, 25, 35),
    # Parmesan is used in the last step but not listed.
    ("810020013", 86013, "Lemon Herb Chicken", "with Orzo & Wilted Spinach", 2, 25, 35),
    # Rice goes into "the pot of boiling water", but no step sets one up.
    ("810020014", 86014, "Black Bean Burrito Bowls", "with Charred Corn Salsa", 2, 20, 30),
    ("810020015", 86015, "Thai Red Curry Shrimp", "with Jasmine Rice & Snap Peas", 2, 25, 30),
    ("810020016", 86016, "Roasted Cauliflower Tacos", "with Avocado Crema", 2, 20, 35),
    # Garnished with toasted sesame seeds, which are not in the ingredient list.
    ("810020017", 86017, "Teriyaki Salmon Bowls", "with Edamame & Pickled Carrots", 2, 25, 30),
    ("810020018", 86018, "Turkey Meatball Spaghetti", "with Marinara & Parmesan", 4, 30, 40),
    # Fresh cilantro is listed but never used.
    ("810020019", 86019, "Coconut Lentil Dal", "with Garlic Naan", 2, 20, 35),
    ("810020020", 86020, "Korean BBQ Tofu", "with Sesame Broccoli & Rice", 2, 25, 30),
)

# recipe_id -> (customer-facing description, amount, unit)
INGREDIENTS: dict[int, tuple[tuple[str, str, str], ...]] = {
    86001: (
        ("Salmon Fillets", "2", ""),
        ("Jasmine Rice", "3/4", "cup"),
        ("Lemon", "1", ""),
        ("Fresh Dill", "1/4", "oz"),
        ("Green Beans", "6", "oz"),
        ("Butter", "2", "tbsp"),
        ("Garlic", "2", "cloves"),
    ),
    86002: (
        ("Boneless Chicken Thighs", "10", "oz"),
        ("Tikka Masala Paste", "2", "tbsp"),
        ("Crushed Tomatoes", "1", "can"),
        ("Basmati Rice", "3/4", "cup"),
        ("Naan", "2", ""),
        ("Heavy Cream", "1/4", "cup"),
        ("Yellow Onion", "1", ""),
    ),
    86003: (
        ("Ground Beef", "10", "oz"),
        ("Bulgogi Sauce", "1/4", "cup"),
        ("Sushi Rice", "3/4", "cup"),
        ("Kimchi", "1/2", "cup"),
        ("Persian Cucumber", "1", ""),
        ("Sesame Seeds", "1", "tbsp"),
        ("Rice Vinegar", "1", "tbsp"),
        ("Gochujang", "1", "tbsp"),
    ),
    86004: (
        ("Arborio Rice", "3/4", "cup"),
        ("Cremini Mushrooms", "6", "oz"),
        ("Parmesan Cheese", "1/4", "cup"),
        ("Fresh Thyme", "2", "sprigs"),
        ("Shallot", "1", ""),
        ("Vegetable Stock Concentrate", "1", "packet"),
        ("Butter", "1", "tbsp"),
    ),
    86005: (
        ("Shrimp", "10", "oz"),
        ("Flour Tortillas", "6", ""),
        ("Lime", "1", ""),
        ("Sour Cream", "1/4", "cup"),
        ("Cabbage Slaw Mix", "4", "oz"),
        ("Chipotle Chile Paste", "1", "tbsp"),
        ("Scallions", "2", ""),
    ),
    86006: (
        ("Ground Pork", "10", "oz"),
        ("Rice Noodles", "6", "oz"),
        ("Pad Thai Sauce", "1/3", "cup"),
        ("Roasted Peanuts", "2", "tbsp"),
        ("Lime", "1", ""),
        ("Bean Sprouts", "2", "oz"),
        ("Carrot", "1", ""),
    ),
    86007: (
        ("Lasagna Noodles", "8", ""),
        ("Ricotta Cheese", "1", "cup"),
        ("Baby Spinach", "5", "oz"),
        ("Marinara Sauce", "1 1/2", "cups"),
        ("Shredded Mozzarella", "1", "cup"),
        ("Zucchini", "2", ""),
        ("Italian Seasoning", "1", "tsp"),
    ),
    86008: (
        ("Cod Fillets", "2", ""),
        ("White Miso Paste", "1", "tbsp"),
        ("Baby Bok Choy", "2", ""),
        ("Jasmine Rice", "3/4", "cup"),
        ("Fresh Ginger", "1", "inch"),
        ("Soy Glaze", "2", "tbsp"),
        ("Scallions", "2", ""),
    ),
    86009: (
        ("Chicken Breast Strips", "10", "oz"),
        ("Bell Peppers", "2", ""),
        ("Red Onion", "1", ""),
        ("Fajita Spice Blend", "1", "tbsp"),
        ("Flour Tortillas", "6", ""),
        ("Sour Cream", "1/4", "cup"),
        ("Lime", "1", ""),
    ),
    86010: (
        ("Potato Gnocchi", "12", "oz"),
        ("Basil Pesto", "1/4", "cup"),
        ("Grape Tomatoes", "6", "oz"),
        ("Fresh Mozzarella", "4", "oz"),
        ("Garlic", "2", "cloves"),
        ("Grated Parmesan", "2", "tbsp"),
    ),
    86011: (
        ("Chickpeas", "1", "can"),
        ("Harissa Paste", "1", "tbsp"),
        ("Farro", "1/2", "cup"),
        ("Greek Yogurt", "1/2", "cup"),
        ("Fresh Parsley", "1/4", "oz"),
        ("Persian Cucumber", "1", ""),
        ("Lemon", "1", ""),
    ),
    86012: (
        ("Sirloin Steaks", "2", ""),
        ("Yukon Gold Potatoes", "12", "oz"),
        ("Butter", "2", "tbsp"),
        ("Garlic", "3", "cloves"),
        ("Baby Arugula", "2", "oz"),
        ("Fresh Rosemary", "1", "sprig"),
        ("Lemon", "1", ""),
    ),
    86013: (
        ("Chicken Breasts", "2", ""),
        ("Orzo", "3/4", "cup"),
        ("Baby Spinach", "3", "oz"),
        ("Lemon", "1", ""),
        ("Garlic", "2", "cloves"),
        ("Italian Herb Blend", "1", "tsp"),
        ("Butter", "1", "tbsp"),
    ),
    86014: (
        ("Black Beans", "1", "can"),
        ("Long-Grain White Rice", "3/4", "cup"),
        ("Corn", "4", "oz"),
        ("Grape Tomatoes", "4", "oz"),
        ("Lime", "1", ""),
        ("Monterey Jack Cheese", "1/4", "cup"),
        ("Southwest Spice Blend", "1", "tbsp"),
    ),
    86015: (
        ("Shrimp", "10", "oz"),
        ("Thai Red Curry Paste", "2", "tbsp"),
        ("Coconut Milk", "1", "can"),
        ("Jasmine Rice", "3/4", "cup"),
        ("Snap Peas", "4", "oz"),
        ("Lime", "1", ""),
        ("Fresh Basil", "1/4", "oz"),
    ),
    86016: (
        ("Cauliflower", "1", "head"),
        ("Corn Tortillas", "6", ""),
        ("Avocado", "1", ""),
        ("Sour Cream", "1/4", "cup"),
        ("Red Cabbage", "4", "oz"),
        ("Taco Spice Blend", "1", "tbsp"),
        ("Lime", "1", ""),
    ),
    86017: (
        ("Salmon Fillets", "2", ""),
        ("Teriyaki Sauce", "1/4", "cup"),
        ("Sushi Rice", "3/4", "cup"),
        ("Shelled Edamame", "4", "oz"),
        ("Carrot", "1", ""),
        ("Rice Vinegar", "1", "tbsp"),
        ("Scallions", "2", ""),
    ),
    86018: (
        ("Ground Turkey", "1", "lb"),
        ("Spaghetti", "12", "oz"),
        ("Marinara Sauce", "2", "cups"),
        ("Panko Breadcrumbs", "1/4", "cup"),
        ("Grated Parmesan", "1/4", "cup"),
        ("Garlic", "3", "cloves"),
        ("Italian Seasoning", "1", "tsp"),
    ),
    86019: (
        ("Red Lentils", "3/4", "cup"),
        ("Coconut Milk", "1", "can"),
        ("Yellow Onion", "1", ""),
        ("Garam Masala", "1", "tbsp"),
        ("Garlic Naan", "2", ""),
        ("Fresh Cilantro", "1/4", "oz"),
        ("Fresh Ginger", "1", "inch"),
    ),
    86020: (
        ("Extra-Firm Tofu", "14", "oz"),
        ("Korean BBQ Sauce", "1/4", "cup"),
        ("Broccoli", "8", "oz"),
        ("Jasmine Rice", "3/4", "cup"),
        ("Sesame Seeds", "1", "tbsp"),
        ("Cornstarch", "2", "tbsp"),
        ("Scallions", "2", ""),
    ),
}
# recipe_id -> (step title, instruction)
STEPS: dict[int, tuple[tuple[str, str], ...]] = {
    86001: (
        (
            "Cook the rice",
            "In a small pot, combine the jasmine rice, 1 1/2 cups water and a pinch "
            "of salt. Bring to a boil, cover and simmer 15 to 17 minutes.",
        ),
        (
            "Make the lemon-dill butter",
            "Zest the lemon and finely chop the dill. In a bowl, mash "
            "the butter with the lemon zest, dill and minced garlic.",
        ),
        (
            "Cook the green beans",
            "In a large pan, heat a drizzle of olive oil on medium-high. Cook "
            "the green beans 5 to 6 minutes, until browned. Transfer to a plate.",
        ),
        (
            "Sear the salmon",
            "Season the salmon fillets with salt and pepper. In the same pan, cook "
            "skin side down 4 to 5 minutes, flip and cook 2 to 3 minutes more.",
        ),
        (
            "Serve",
            "Stir half the lemon-dill butter into the rice. Serve the salmon over the rice "
            "with the green beans, topped with the remaining lemon-dill butter and a squeeze of lemon "
            "juice.",
        ),
    ),
    86002: (
        (
            "Cook the rice",
            "In a small pot, combine the basmati rice, 1 1/2 cups water and a pinch "
            "of salt. Bring to a boil, cover and simmer 12 to 14 minutes.",
        ),
        (
            "Brown the chicken",
            "Dice the onion. Season the chicken thighs with salt and pepper. In a "
            "large pan, heat a drizzle of olive oil and cook the chicken 4 to 5 minutes per side.",
        ),
        (
            "Make the sauce",
            "Add the onion and tikka masala paste to the pan and cook 2 minutes. Stir "
            "in the crushed tomatoes and simmer 8 to 10 minutes. Stir in the heavy cream.",
        ),
        ("Warm the naan", "Wrap the naan in foil and warm in a 425°F oven 4 to 5 minutes."),
        ("Serve", "Serve the chicken and sauce over the rice with the warm naan on the side."),
    ),
    86003: (
        (
            "Cook the rice",
            "In a small pot, combine the sushi rice and 1 cup water. Bring to a boil, "
            "cover and simmer 15 minutes.",
        ),
        (
            "Quick-pickle the cucumber",
            "Thinly slice the cucumber and toss with the rice vinegar and a pinch of salt.",
        ),
        (
            "Cook the beef",
            "In a large pan, heat a drizzle of neutral oil on medium-high. Cook the "
            "ground beef 4 to 5 minutes, breaking it up. Stir in the bulgogi sauce and cook 1 minute.",
        ),
        (
            "Assemble the bowls",
            "Divide the rice between bowls. Top with the beef, kimchi and "
            "pickled cucumber. Garnish with the sesame seeds.",
        ),
    ),
    86004: (
        (
            "Prepare the ingredients",
            "Slice the mushrooms. Mince the shallot. Pick the thyme leaves. "
            "In a pot, heat 4 cups water with the stock concentrate and keep it warm.",
        ),
        (
            "Brown the mushrooms",
            "In a large pot, heat a drizzle of olive oil on medium-high. Cook "
            "the mushrooms 5 to 6 minutes, until browned. Transfer to a plate.",
        ),
        (
            "Toast the rice",
            "In the same pot, cook the shallot and arborio rice 2 minutes, stirring.",
        ),
        (
            "Cook the risotto",
            "Add the warm stock 1 cup at a time, stirring until absorbed before "
            "adding more, 20 to 22 minutes total.",
        ),
        (
            "Finish and serve",
            "Stir in the mushrooms, butter, thyme and parmesan cheese. Season with "
            "salt and pepper and serve.",
        ),
    ),
    86005: (
        (
            "Make the lime crema",
            "Zest and juice the lime. In a bowl, combine the sour cream with "
            "half the lime juice and a pinch of the zest.",
        ),
        (
            "Dress the slaw",
            "Toss the cabbage slaw mix with the remaining lime juice and a pinch of salt.",
        ),
        (
            "Cook the shrimp",
            "Toss the shrimp with the chipotle chile paste. In a large pan, heat a "
            "drizzle of olive oil and cook 2 to 3 minutes per side.",
        ),
        ("Warm the tortillas", "Warm the flour tortillas in a dry pan 30 seconds per side."),
        (
            "Assemble the tacos",
            "Fill the tortillas with the shrimp and slaw. Top with the lime crema and the "
            "chopped cilantro.",
        ),
    ),
    86006: (
        (
            "Soak the noodles",
            "Place the rice noodles in a bowl and cover with hot water. Soak 8 to "
            "10 minutes, then drain.",
        ),
        ("Prepare the vegetables", "Peel and grate the carrot. Cut the lime into wedges."),
        (
            "Cook the pork",
            "In a large pan, heat a drizzle of neutral oil on medium-high. Cook the "
            "ground pork and carrot 4 to 5 minutes.",
        ),
        (
            "Toss with the sauce",
            "Add the noodles and pad thai sauce. Cook, tossing, 2 to 3 minutes. "
            "Stir in the bean sprouts.",
        ),
        (
            "Serve",
            "Top the pad thai with the peanuts and the chopped cilantro. Serve with the lime "
            "wedges.",
        ),
    ),
    86007: (
        ("Preheat and prepare", "Preheat the oven. Cut the zucchini into half-moons."),
        (
            "Make the filling",
            "In a bowl, combine the ricotta cheese, chopped spinach, Italian "
            "seasoning and a pinch of salt.",
        ),
        (
            "Layer the lasagna",
            "In a baking dish, layer marinara sauce, lasagna noodles and the "
            "ricotta filling. Repeat, finishing with sauce and the shredded mozzarella.",
        ),
        (
            "Bake",
            "Cover with foil and bake 35 minutes. Uncover and bake 10 minutes more, until "
            "bubbly. Roast the zucchini on a sheet pan alongside for the last 20 minutes.",
        ),
        (
            "Rest and serve",
            "Let the lasagna rest 10 minutes before slicing. Serve with the roasted zucchini.",
        ),
    ),
    86008: (
        (
            "Cook the rice",
            "In a small pot, combine the jasmine rice, 1 1/2 cups water and a pinch "
            "of salt. Bring to a boil, cover and simmer 15 minutes.",
        ),
        (
            "Glaze the cod",
            "Preheat the broiler. Whisk the miso paste with the soy glaze. Brush over "
            "the cod fillets and broil 8 to 10 minutes.",
        ),
        (
            "Cook the bok choy",
            "Halve the bok choy and peel and grate the ginger. In a pan, heat a "
            "drizzle of neutral oil and cook the bok choy with the ginger 3 to 4 minutes.",
        ),
        (
            "Serve",
            "Serve the cod over the rice with the bok choy. Garnish with the sliced scallions.",
        ),
    ),
    86009: (
        (
            "Prepare the vegetables",
            "Preheat the oven to 450°F. Slice the bell peppers and red onion into strips.",
        ),
        (
            "Roast the fajitas",
            "On a sheet pan, toss the chicken, peppers and onion with the fajita "
            "spice blend and a drizzle of olive oil. Roast 18 to 20 minutes.",
        ),
        (
            "Char the tortillas",
            "In the same skillet, char the flour tortillas over medium-high heat "
            "30 seconds per side.",
        ),
        ("Serve", "Squeeze the lime over the fajitas. Serve in the tortillas with the sour cream."),
    ),
    86010: (
        (
            "Blister the tomatoes",
            "In a large pan, heat a drizzle of olive oil on medium-high. Cook "
            "the grape tomatoes and sliced garlic 4 to 5 minutes, until blistered. Transfer to a "
            "bowl.",
        ),
        (
            "Cook the gnocchi",
            "In the same pan, cook the gnocchi with a drizzle of olive oil 6 to 8 "
            "minutes, until golden.",
        ),
        (
            "Finish and serve",
            "Stir in the basil pesto and the tomatoes. Top with torn fresh "
            "mozzarella and the grated parmesan.",
        ),
    ),
    86011: (
        (
            "Cook the farro",
            "Bring a large pot of salted water to a boil. Cook the farro 22 to 25 minutes. Drain.",
        ),
        (
            "Make the herbed yogurt",
            "Chop the parsley. Stir the Greek yogurt with the parsley and "
            "the juice of half the lemon.",
        ),
        (
            "Roast the chickpeas",
            "Preheat the oven to 425°F. Toss the drained chickpeas with the "
            "harissa paste and roast 15 minutes.",
        ),
        (
            "Dress the farro",
            "Toss the cooked farro with all of the herbed yogurt and the diced cucumber.",
        ),
        (
            "Serve",
            "Top the farro with the harissa chickpeas and drizzle with the remaining herbed "
            "yogurt. Serve with the remaining lemon cut into wedges.",
        ),
    ),
    86012: (
        (
            "Boil the potatoes",
            "Bring a large pot of salted water to a boil. Cook the potatoes 15 to 18 minutes, "
            "until tender. Drain.",
        ),
        (
            "Smash and crisp",
            "In a large pan, heat a drizzle of olive oil. Smash the potatoes and "
            "cook 4 to 5 minutes per side, until crisp.",
        ),
        (
            "Cook the steaks",
            "Season the steaks with salt and pepper. In the same pan, cook 3 to 4 "
            "minutes per side. Add the butter, crushed garlic and rosemary and baste 1 minute.",
        ),
        (
            "Serve",
            "Toss the arugula with a squeeze of lemon juice. Serve the sliced steaks with the "
            "potatoes and arugula, spooning the garlic butter over the top.",
        ),
    ),
    86013: (
        (
            "Cook the orzo",
            "Bring a medium pot of salted water to a boil. Cook the orzo 8 to 9 minutes, "
            "then drain.",
        ),
        (
            "Cook the chicken",
            "Season the chicken breasts with the Italian herb blend, salt and pepper. "
            "In a large pan, heat a drizzle of olive oil and cook 5 to 6 minutes per side. Transfer to "
            "a board.",
        ),
        (
            "Make the pan sauce",
            "In the same pan, cook the minced garlic 30 seconds. Add the juice of "
            "the lemon, the butter and 2 tbsp water and stir until glossy.",
        ),
        (
            "Wilt the spinach and serve",
            "Stir the spinach and orzo into the pan until wilted. Serve "
            "with the sliced chicken and lemon wedges, finished with the grated parmesan.",
        ),
    ),
    86014: (
        (
            "Prepare the ingredients",
            "Halve the tomatoes. Quarter the lime. Drain and rinse the black beans.",
        ),
        (
            "Cook the rice",
            "Add the rice to the pot of boiling water and cook 12 to 14 minutes. Drain "
            "and return to the pot.",
        ),
        (
            "Char the corn",
            "In a large pan, heat a drizzle of olive oil on high. Cook the corn 4 to 5 "
            "minutes, until charred. Toss with the tomatoes and the juice of half the lime.",
        ),
        (
            "Warm the beans",
            "In the same pan, cook the black beans with the southwest spice blend and "
            "1/4 cup water 3 to 4 minutes.",
        ),
        (
            "Assemble the bowls",
            "Divide the rice between bowls. Top with the beans, corn salsa and "
            "Monterey Jack cheese. Serve with the remaining lime wedges.",
        ),
    ),
    86015: (
        (
            "Cook the rice",
            "In a small pot, combine the jasmine rice, 1 1/2 cups water and a pinch of "
            "salt. Bring to a boil, cover and simmer 15 minutes.",
        ),
        (
            "Start the curry",
            "In a large pan, heat a drizzle of neutral oil. Cook the red curry paste "
            "1 minute, then stir in the coconut milk and simmer 5 minutes.",
        ),
        (
            "Cook the shrimp and peas",
            "Add the shrimp and snap peas to the curry and cook 3 to 4 "
            "minutes, until the shrimp are opaque. Stir in the juice of the lime.",
        ),
        ("Serve", "Serve the curry over the rice, topped with torn basil leaves."),
    ),
    86016: (
        (
            "Roast the cauliflower",
            "Preheat the oven to 450°F. Cut the cauliflower into florets, toss "
            "with the taco spice blend and a drizzle of olive oil and roast 20 to 22 minutes.",
        ),
        (
            "Make the avocado crema",
            "Mash the avocado with the sour cream and the juice of half the "
            "lime. Season with salt.",
        ),
        ("Make the slaw", "Thinly slice the cabbage and toss with the remaining lime juice."),
        ("Warm the tortillas", "Warm the corn tortillas in a dry pan 30 seconds per side."),
        (
            "Assemble the tacos",
            "Fill the tortillas with the cauliflower and slaw. Top with the avocado crema.",
        ),
    ),
    86017: (
        (
            "Cook the rice",
            "In a small pot, combine the sushi rice and 1 cup water. Bring to a boil, "
            "cover and simmer 15 minutes.",
        ),
        (
            "Pickle the carrot",
            "Peel the carrot into ribbons and toss with the rice vinegar and a pinch of salt.",
        ),
        (
            "Cook the salmon",
            "In a large pan, heat a drizzle of neutral oil. Cook the salmon 4 minutes, "
            "flip, add the teriyaki sauce and cook 2 to 3 minutes, spooning the glaze over.",
        ),
        ("Warm the edamame", "Microwave the edamame with 1 tbsp water 1 to 2 minutes."),
        (
            "Assemble the bowls",
            "Divide the rice between bowls. Top with the salmon, edamame and "
            "pickled carrot. Garnish with the sliced scallions and the toasted sesame seeds.",
        ),
    ),
    86018: (
        (
            "Make the meatballs",
            "Preheat the oven to 425°F. Combine the ground turkey, panko "
            "breadcrumbs, minced garlic, Italian seasoning and half the parmesan. Form 12 meatballs and "
            "roast 15 to 18 minutes.",
        ),
        (
            "Cook the pasta",
            "Bring a large pot of salted water to a boil. Cook the spaghetti 9 to 10 "
            "minutes, then drain.",
        ),
        (
            "Simmer the sauce",
            "In a large pan, warm the marinara sauce. Add the meatballs and simmer 5 minutes.",
        ),
        (
            "Serve",
            "Toss the spaghetti with some of the sauce. Top with the meatballs, the remaining "
            "sauce and the remaining parmesan.",
        ),
    ),
    86019: (
        (
            "Start the dal",
            "Dice the onion and grate the ginger. In a pot, heat a drizzle of neutral "
            "oil and cook the onion 4 to 5 minutes. Add the ginger and garam masala and cook 1 minute.",
        ),
        (
            "Simmer the lentils",
            "Add the red lentils, coconut milk and 1 cup water. Simmer 18 to 20 "
            "minutes, stirring, until thick.",
        ),
        ("Warm the naan", "Warm the garlic naan in a 400°F oven 4 to 5 minutes."),
        ("Serve", "Season the dal with salt and serve with the warm naan."),
    ),
    86020: (
        (
            "Cook the rice",
            "In a small pot, combine the jasmine rice, 1 1/2 cups water and a pinch of "
            "salt. Bring to a boil, cover and simmer 15 minutes.",
        ),
        (
            "Crisp the tofu",
            "Cut the tofu into cubes and toss with the cornstarch. In a large pan, "
            "heat a drizzle of neutral oil and cook 8 to 10 minutes, turning, until crisp.",
        ),
        (
            "Glaze the tofu",
            "Add the Korean BBQ sauce to the pan and toss to coat. Transfer to a plate.",
        ),
        (
            "Cook the broccoli",
            "In the same pan, cook the broccoli with 2 tbsp water 4 to 5 minutes. "
            "Sprinkle with the sesame seeds.",
        ),
        (
            "Serve",
            "Serve the tofu and broccoli over the rice, garnished with the sliced scallions.",
        ),
    ),
}


def _mondays(today: dt.date, back: int, ahead: int) -> list[dt.date]:
    monday = today - dt.timedelta(days=today.weekday())
    return [monday + dt.timedelta(weeks=w) for w in range(-back, ahead + 1)]


def _runs(today: dt.date) -> list[tuple[int, dt.date, str]]:
    """recipe_id, cycle, slot: every recipe runs this week, most also once before."""
    this_week = today - dt.timedelta(days=today.weekday())
    runs = []
    for index, (_, recipe_id, *_rest) in enumerate(RECIPES):
        if index % 3 != 2:
            earlier = this_week - dt.timedelta(weeks=3 + index % 4)
            runs.append((recipe_id, earlier, str((index + 5) % 12 + 1)))
        runs.append((recipe_id, this_week, str(index + 1)))
    return sorted(runs, key=lambda run: (run[1], int(run[2])))


def _ts(today: dt.date) -> str:
    return dt.datetime.combine(today, dt.time(6), tzinfo=dt.UTC).isoformat()


def _url(sku: str) -> str:
    return f"https://recipes.example.com/{sku}"


def _products(today: dt.date) -> Iterator[Row]:
    runs = _runs(today)
    for sku, recipe_id, title, subtitle, servings, active, total in RECIPES:
        yield {
            "recipe_sku": sku,
            "product_name": title,
            "product_subtitle": subtitle,
            "customization_description": None,
            "customization_of_recipe_sku": None,
            "servings": servings,
            "active_cook_time": active,
            "total_cook_time": total,
            "delivery_cycles": [c.isoformat() for r, c, _ in runs if r == recipe_id],
            "recipe_url": _url(sku),
            "is_deleted": False,
            "last_updated_at": _ts(today),
            "bq_ingested_at": _ts(today),
        }


def _product_steps(today: dt.date) -> Iterator[Row]:
    for sku, recipe_id, *_ in RECIPES:
        for number, (title, text) in enumerate(STEPS[recipe_id], start=1):
            yield {
                "recipe_sku": sku,
                "step_number": number,
                "step_title": title,
                "instruction": text,
                "last_updated_at": _ts(today),
                "bq_ingested_at": _ts(today),
            }


def _cycles(today: dt.date) -> Iterator[Row]:
    for n, cycle in enumerate(_mondays(today, back=8, ahead=2), start=1):
        status = (
            "past"
            if cycle + dt.timedelta(days=6) < today
            else ("current" if cycle <= today else "upcoming")
        )
        yield {
            "cycle_id": 9000 + n,
            "cycle": cycle.isoformat(),
            "cycle_status": status,
            "cycle_start_date_et": cycle.isoformat(),
            "cycle_end_date_et": (cycle + dt.timedelta(days=6)).isoformat(),
        }


def _menu_items(today: dt.date) -> Iterator[Row]:
    by_id = {r[1]: r for r in RECIPES}
    for recipe_id, cycle, _ in _runs(today):
        sku, _, title, subtitle, *_ = by_id[recipe_id]
        yield {
            "recipe_sku": sku,
            "cycle": cycle.isoformat(),
            "main_name": title,
            "display_name": f"{title} {subtitle}",
            "subtitle": subtitle,
            "customization_display_name": None,
            "recipe_url": _url(sku),
            "is_visible": True,
        }


def _product_ingredients(today: dt.date) -> Iterator[Row]:
    del today
    for sku, recipe_id, *_ in RECIPES:
        for n, (name, amount, unit) in enumerate(INGREDIENTS[recipe_id], start=1):
            yield {
                "recipe_sku": sku,
                "ingredient_sku": f"ING-{recipe_id}-{n:02d}",
                "ingredient_name": name.lower(),
                "amount": float(len(amount)),
                "units": unit or "each",
            }


def _ingredient_specs(today: dt.date) -> Iterator[Row]:
    del today
    for _, recipe_id, *_ in RECIPES:
        for n, (name, *_rest) in enumerate(INGREDIENTS[recipe_id], start=1):
            lower = name.lower()
            yield {
                "ingredient_sku": f"ING-{recipe_id}-{n:02d}",
                "ingredient_name": lower,
                "category": "protein" if n == 1 else "pantry",
                "allergens": "fish" if any(w in lower for w in ("salmon", "cod")) else None,
            }


def _legacy_recipes(today: dt.date) -> Iterator[Row]:
    first = {}
    for recipe_id, cycle, slot in _runs(today):
        first.setdefault(recipe_id, (cycle, slot))
    for sku, recipe_id, title, subtitle, servings, *_ in RECIPES:
        cycle, slot = first[recipe_id]
        yield {
            "recipe_id": recipe_id,
            "recipe_sku": sku,
            "recipe_title": title,
            "recipe_sub_title": subtitle,
            "recipe_cycle_date": cycle.isoformat(),
            "recipe_status": "active",
            "recipe_slot_short_code": slot,
            "recipe_slot_plan": f"{servings}-serving",
            "recipe_customization_variable": None,
            "recipe_customization_ingredient_diff": None,
            "recipe_archived_at": None,
            "updated_at": _ts(today),
        }


def _legacy_steps(today: dt.date) -> Iterator[Row]:
    step_id = 500000
    for _, recipe_id, *_ in RECIPES:
        for order, (title, text) in enumerate(STEPS[recipe_id], start=1):
            step_id += 1
            yield {
                "recipe_step_id": step_id,
                "recipe_id": recipe_id,
                "step_title": title,
                "step_text": text,
                "recipe_step_sort_order": order,
                "updated_at": _ts(today),
            }


def _legacy_ingredients(today: dt.date) -> Iterator[Row]:
    first = {}
    for recipe_id, cycle, _ in _runs(today):
        first.setdefault(recipe_id, cycle)
    ingredient_id = 700000
    for _, recipe_id, *_ in RECIPES:
        # Version 2 is current; version 1 is an older revision the agent must ignore.
        for version in (1, 2):
            for n, (name, amount, unit) in enumerate(INGREDIENTS[recipe_id], start=1):
                ingredient_id += 1
                if version == 1 and n == 1:
                    name = f"{name} (old spec)"
                yield {
                    "recipe_id": recipe_id,
                    "recipe_ingredient_id": ingredient_id,
                    "recipe_cycle_date": first[recipe_id].isoformat(),
                    "recipe_version_number": version,
                    "recipe_ingredient_customer_facing_description": name,
                    "recipe_ingredient_customer_facing_amount": amount,
                    "recipe_ingredient_customer_facing_unit": unit,
                    "recipe_ingredient_sku_master_sku": f"ING-{recipe_id}-{n:02d}",
                    "updated_at": _ts(today),
                }


def _slots(today: dt.date) -> Iterator[Row]:
    by_id = {r[1]: r[0] for r in RECIPES}
    for n, (recipe_id, cycle, slot) in enumerate(_runs(today), start=1):
        yield {
            "cycle_recipe_id": 800000 + n,
            "cycle_date": cycle.isoformat(),
            "recipe_slot_short_code": slot,
            "recipe_id": recipe_id,
            "cycle_sku": f"{by_id[recipe_id]}{cycle:%y%m%d}",
            "recipe_status": "scheduled" if cycle > today else "delivered",
            "recipe_customization_variable": None,
            "recipe_core": True,
            "updated_at": _ts(today),
        }


def _schema(*columns: str) -> tuple[tuple[str, str, str], ...]:
    """name:TYPE[:MODE] shorthand for the recipe tables."""
    out = []
    for column in columns:
        name, kind, *mode = column.split(":")
        out.append((name, kind, mode[0] if mode else "NULLABLE"))
    return tuple(out)


TABLES = (
    Table(KITCHEN_DATASET, "order_compliance_daily", ORDER_SCHEMA, _orders, "service_date_et"),
    Table(KITCHEN_DATASET, "kitchen_compliance_items", ITEM_SCHEMA, _items, "service_date_et"),
    Table(
        RECIPE_PRODUCT_DATASET,
        "culinary_products",
        _schema(
            "recipe_sku:STRING",
            "product_name:STRING",
            "product_subtitle:STRING",
            "customization_description:STRING",
            "customization_of_recipe_sku:STRING",
            "servings:INTEGER",
            "active_cook_time:INTEGER",
            "total_cook_time:INTEGER",
            "delivery_cycles:DATE:REPEATED",
            "recipe_url:STRING",
            "is_deleted:BOOLEAN",
            "last_updated_at:TIMESTAMP",
            "bq_ingested_at:TIMESTAMP",
        ),
        _products,
    ),
    Table(
        RECIPE_PRODUCT_DATASET,
        "culinary_product_preparation_steps",
        _schema(
            "recipe_sku:STRING",
            "step_number:INTEGER",
            "step_title:STRING",
            "instruction:STRING",
            "last_updated_at:TIMESTAMP",
            "bq_ingested_at:TIMESTAMP",
        ),
        _product_steps,
    ),
    Table(
        RECIPE_PRODUCT_DATASET,
        "menu_cycles",
        _schema(
            "cycle_id:INTEGER",
            "cycle:DATE",
            "cycle_status:STRING",
            "cycle_start_date_et:DATE",
            "cycle_end_date_et:DATE",
        ),
        _cycles,
    ),
    Table(
        RECIPE_PRODUCT_DATASET,
        "menu_items",
        _schema(
            "recipe_sku:STRING",
            "cycle:DATE",
            "main_name:STRING",
            "display_name:STRING",
            "subtitle:STRING",
            "customization_display_name:STRING",
            "recipe_url:STRING",
            "is_visible:BOOLEAN",
        ),
        _menu_items,
    ),
    Table(
        RECIPE_PRODUCT_DATASET,
        "culinary_product_ingredients",
        _schema(
            "recipe_sku:STRING",
            "ingredient_sku:STRING",
            "ingredient_name:STRING",
            "amount:FLOAT",
            "units:STRING",
        ),
        _product_ingredients,
    ),
    Table(
        RECIPE_PRODUCT_DATASET,
        "culinary_ingredient_specifications",
        _schema(
            "ingredient_sku:STRING",
            "ingredient_name:STRING",
            "category:STRING",
            "allergens:STRING",
        ),
        _ingredient_specs,
    ),
    Table(
        RECIPE_LEGACY_DATASET,
        "legacy_recipes",
        _schema(
            "recipe_id:INTEGER",
            "recipe_sku:STRING",
            "recipe_title:STRING",
            "recipe_sub_title:STRING",
            "recipe_cycle_date:DATE",
            "recipe_status:STRING",
            "recipe_slot_short_code:STRING",
            "recipe_slot_plan:STRING",
            "recipe_customization_variable:STRING",
            "recipe_customization_ingredient_diff:STRING",
            "recipe_archived_at:TIMESTAMP",
            "updated_at:TIMESTAMP",
        ),
        _legacy_recipes,
    ),
    Table(
        RECIPE_LEGACY_DATASET,
        "legacy_recipe_steps",
        _schema(
            "recipe_step_id:INTEGER",
            "recipe_id:INTEGER",
            "step_title:STRING",
            "step_text:STRING",
            "recipe_step_sort_order:INTEGER",
            "updated_at:TIMESTAMP",
        ),
        _legacy_steps,
    ),
    Table(
        RECIPE_LEGACY_DATASET,
        "legacy_recipe_ingredients",
        _schema(
            "recipe_id:INTEGER",
            "recipe_ingredient_id:INTEGER",
            "recipe_cycle_date:DATE",
            "recipe_version_number:INTEGER",
            "recipe_ingredient_customer_facing_description:STRING",
            "recipe_ingredient_customer_facing_amount:STRING",
            "recipe_ingredient_customer_facing_unit:STRING",
            "recipe_ingredient_sku_master_sku:STRING",
            "updated_at:TIMESTAMP",
        ),
        _legacy_ingredients,
    ),
    Table(
        RECIPE_LEGACY_DATASET,
        "legacy_cycle_recipe_slots",
        _schema(
            "cycle_recipe_id:INTEGER",
            "cycle_date:DATE",
            "recipe_slot_short_code:STRING",
            "recipe_id:INTEGER",
            "cycle_sku:STRING",
            "recipe_status:STRING",
            "recipe_customization_variable:STRING",
            "recipe_core:BOOLEAN",
            "updated_at:TIMESTAMP",
        ),
        _slots,
    ),
)


def today_eastern() -> dt.date:
    return dt.datetime.now(EASTERN).date()


def load_sample_data(project_id: str, location: str | None = None) -> dict[str, int]:
    """Create the three datasets if missing and replace every sample table."""
    import os

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    location = location or os.getenv(LOCATION_ENV, "").strip() or DEFAULT_LOCATION
    client = bigquery.Client(project=project_id)
    today = today_eastern()
    for dataset in {table.dataset for table in TABLES}:
        reference = f"{project_id}.{dataset}"
        try:
            client.get_dataset(reference)
        except NotFound:
            created = bigquery.Dataset(reference)
            created.location = location
            created.description = "Synthetic sample data for demonstrating the agents. Not real."
            created.labels = {"managed_by": "gemini-agent-repo", "purpose": "sample-data"}
            client.create_dataset(created)
            print(f"SAMPLE_DATASET_CREATED={reference}")

    loaded: dict[str, int] = {}
    for table in TABLES:
        rows = list(table.rows(today))
        config = bigquery.LoadJobConfig(
            schema=[bigquery.SchemaField(n, t, mode=m) for n, t, m in table.schema],
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )
        if table.partition_field:
            config.time_partitioning = bigquery.TimePartitioning(field=table.partition_field)
        reference = f"{project_id}.{table.dataset}.{table.name}"
        client.load_table_from_json(rows, reference, job_config=config, location=location).result()
        loaded[f"{table.dataset}.{table.name}"] = len(rows)
        print(f"SAMPLE_TABLE_LOADED={reference} rows={len(rows)}")
    return loaded
