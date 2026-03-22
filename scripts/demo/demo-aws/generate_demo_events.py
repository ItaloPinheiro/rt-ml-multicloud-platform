#!/usr/bin/env python
"""Generate a deterministic set of demo events for reproducible demos.

Produces a fixed JSON-lines file with curated transaction events that,
when processed through the Beam pipeline and labeled by RuleBasedLabeling,
yield a training dataset where:

  - v1 (10 trees, depth 1, no class weight) predicts everything as not-fraud
  - v2 (200 trees, depth 5, class_weight=balanced) catches fraud

The events match the exact schema expected by the Kinesis producer
(publish_kinesis_events.py) so they can be published to Kinesis or
loaded directly into the Feature Store.

Usage:
  # Generate events file
  python generate_demo_events.py

  # Generate and preview label distribution (dry run)
  python generate_demo_events.py --preview

Output:
  data/sample/demo/events/demo_events.jsonl
"""

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Event templates — deterministic "recipes" for realistic transaction mixes
# ---------------------------------------------------------------------------

# Labeling risk accumulation reference (threshold = 0.65):
#   merchant base rate: grocery=0.01, gas_station=0.02, restaurant=0.03,
#     pharmacy=0.01, clothing=0.04, online_retail=0.06, electronics=0.08,
#     travel=0.10, jewelry=0.15, cash_advance=0.25
#   night (hour < 6 or >= 22): +0.2
#   amount > 1000: +0.3
#   high-risk category (jewelry, cash_advance): +0.4
#   weekend cash advance: +0.3

LEGITIMATE_PROFILES = [
    # Everyday low-risk: business hours, low amounts, safe merchants
    {
        "merchant_category": "grocery",
        "amount_range": (15, 120),
        "hours": (8, 18),
        "weekend_ratio": 0.3,
        "payment_methods": ["credit_card", "debit_card"],
        "count": 95,
    },
    {
        "merchant_category": "gas_station",
        "amount_range": (25, 80),
        "hours": (6, 20),
        "weekend_ratio": 0.4,
        "payment_methods": ["credit_card", "debit_card"],
        "count": 50,
    },
    {
        "merchant_category": "restaurant",
        "amount_range": (12, 90),
        "hours": (11, 22),
        "weekend_ratio": 0.5,
        "payment_methods": ["credit_card", "digital_wallet"],
        "count": 55,
    },
    {
        "merchant_category": "pharmacy",
        "amount_range": (5, 60),
        "hours": (8, 20),
        "weekend_ratio": 0.2,
        "payment_methods": ["debit_card", "credit_card"],
        "count": 35,
    },
    {
        "merchant_category": "clothing",
        "amount_range": (20, 200),
        "hours": (10, 19),
        "weekend_ratio": 0.6,
        "payment_methods": ["credit_card", "digital_wallet"],
        "count": 35,
    },
    {
        "merchant_category": "online_retail",
        "amount_range": (10, 300),
        "hours": (7, 23),
        "weekend_ratio": 0.4,
        "payment_methods": ["credit_card", "digital_wallet"],
        "count": 40,
    },
    {
        "merchant_category": "electronics",
        "amount_range": (50, 800),
        "hours": (9, 20),
        "weekend_ratio": 0.4,
        "payment_methods": ["credit_card", "bank_transfer"],
        "count": 25,
    },
    {
        "merchant_category": "travel",
        "amount_range": (100, 900),
        "hours": (8, 22),
        "weekend_ratio": 0.3,
        "payment_methods": ["credit_card", "bank_transfer"],
        "count": 25,
    },
    # Confusing cases: high amounts that are NOT fraud (daytime, safe merchant)
    # These force v1 to fail — depth-1 trees that split on amount will
    # incorrectly flag these as fraud.
    {
        "merchant_category": "electronics",
        "amount_range": (1200, 2500),
        "hours": (10, 16),
        "weekend_ratio": 0.2,
        "payment_methods": ["credit_card", "bank_transfer"],
        "count": 15,
        "description": "high-amount legitimate electronics (daytime)",
    },
    {
        "merchant_category": "travel",
        "amount_range": (1500, 4000),
        "hours": (9, 17),
        "weekend_ratio": 0.3,
        "payment_methods": ["credit_card"],
        "count": 12,
        "description": "high-amount legitimate travel (daytime)",
    },
    # Confusing cases: night transactions that are NOT fraud (low amounts)
    {
        "merchant_category": "pharmacy",
        "amount_range": (5, 30),
        "hours": (22, 5),
        "weekend_ratio": 0.3,
        "payment_methods": ["debit_card"],
        "count": 12,
        "description": "night pharmacy runs (low amount, not fraud)",
    },
    {
        "merchant_category": "gas_station",
        "amount_range": (20, 60),
        "hours": (22, 5),
        "weekend_ratio": 0.3,
        "payment_methods": ["credit_card"],
        "count": 12,
        "description": "night gas station (low amount, not fraud)",
    },
]

# Total legitimate: 411  |  Total fraud: 89  |  Grand total: 500
# Fraud rate: ~17.8% (RuleBasedLabeling will produce ~15% after noise)

FRAUD_PROFILES = [
    # Cash advance at night with high amount
    # Risk: 0.25 (base) + 0.4 (high-risk) + 0.2 (night) + 0.3 (high amount) = 1.15
    {
        "merchant_category": "cash_advance",
        "amount_range": (2000, 5000),
        "hours": (0, 5),
        "weekend_ratio": 0.6,
        "payment_methods": ["credit_card", "debit_card"],
        "count": 30,
    },
    # Weekend cash advance with high amount (any hour)
    # Risk: 0.25 + 0.4 + 0.3 (weekend) + 0.3 (amount) = 1.25
    {
        "merchant_category": "cash_advance",
        "amount_range": (1500, 4500),
        "hours": (6, 21),
        "weekend_ratio": 1.0,  # always weekend
        "payment_methods": ["credit_card"],
        "count": 18,
    },
    # Jewelry at night with high amount
    # Risk: 0.15 + 0.4 + 0.2 (night) + 0.3 (amount) = 1.05
    {
        "merchant_category": "jewelry",
        "amount_range": (2000, 8000),
        "hours": (0, 5),
        "weekend_ratio": 0.5,
        "payment_methods": ["credit_card"],
        "count": 18,
    },
    # Cash advance at night, moderate amount (still fraud without high-amount bonus)
    # Risk: 0.25 + 0.4 + 0.2 (night) = 0.85 > 0.65
    {
        "merchant_category": "cash_advance",
        "amount_range": (200, 900),
        "hours": (0, 5),
        "weekend_ratio": 0.4,
        "payment_methods": ["debit_card"],
        "count": 12,
    },
    # Jewelry at night, moderate amount
    # Risk: 0.15 + 0.4 + 0.2 (night) = 0.75 > 0.65
    {
        "merchant_category": "jewelry",
        "amount_range": (300, 900),
        "hours": (22, 4),
        "weekend_ratio": 0.5,
        "payment_methods": ["credit_card"],
        "count": 11,
    },
]


def _deterministic_value(seed: int, low: float, high: float) -> float:
    """Generate a deterministic value in [low, high] from a seed.

    Uses a simple linear congruential generator for reproducibility
    without importing random (avoids global state pollution).
    """
    # LCG parameters (Numerical Recipes)
    x = ((seed * 1664525 + 1013904223) & 0xFFFFFFFF) / 0xFFFFFFFF
    return round(low + x * (high - low), 2)


def _deterministic_choice(seed: int, options: list):
    """Pick from a list deterministically."""
    idx = ((seed * 1664525 + 1013904223) & 0xFFFFFFFF) % len(options)
    return options[idx]


def _make_hour(seed: int, hour_start: int, hour_end: int) -> int:
    """Generate an hour in the given range, wrapping around midnight."""
    if hour_start < hour_end:
        hours = list(range(hour_start, hour_end))
    else:
        # Wraps midnight: e.g., 22..5 -> [22,23,0,1,2,3,4]
        hours = list(range(hour_start, 24)) + list(range(0, hour_end))
    return _deterministic_choice(seed, hours)


def generate_events() -> list[dict]:
    """Generate the full deterministic demo event set."""
    events = []
    base_time = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    event_idx = 0
    user_pool_size = 200

    all_profiles = [(profile, False) for profile in LEGITIMATE_PROFILES] + [
        (profile, True) for profile in FRAUD_PROFILES
    ]

    for profile, _is_fraud_profile in all_profiles:
        for i in range(profile["count"]):
            seed = event_idx * 7919 + i * 131  # deterministic seed

            # Deterministic user assignment (spread across user pool)
            # 37 is coprime with 200, so this cycles through all user IDs
            # before repeating, giving each user 2-3 events on average.
            user_num = (event_idx * 37) % user_pool_size + 1
            user_id = f"user_{user_num}"

            # Deterministic timestamp spread across 30 days
            day_offset = event_idx % 30
            hour = _make_hour(seed, profile["hours"][0], profile["hours"][1])
            minute = ((seed * 31) & 0xFF) % 60
            second = ((seed * 17) & 0xFF) % 60

            # Determine weekend: use profile ratio deterministically
            is_weekend_event = (
                _deterministic_value(seed + 999, 0, 1) < profile["weekend_ratio"]
            )
            if is_weekend_event:
                # Map to Saturday (5) or Sunday (6)
                day_of_week = 5 + (event_idx % 2)
                # Adjust day_offset to land on a weekend
                day_offset = day_offset - (day_offset % 7) + day_of_week
            else:
                # Map to a weekday (0-4)
                day_of_week = event_idx % 5
                day_offset = day_offset - (day_offset % 7) + day_of_week

            day_offset = max(0, min(day_offset, 29))

            timestamp = base_time - timedelta(
                days=day_offset, hours=24 - hour, minutes=minute, seconds=second
            )

            amount = _deterministic_value(
                seed + 42, profile["amount_range"][0], profile["amount_range"][1]
            )

            payment_method = _deterministic_choice(
                seed + 77, profile["payment_methods"]
            )

            event = {
                "event_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-{event_idx}")),
                "user_id": user_id,
                "amount": amount,
                "timestamp": timestamp.isoformat(),
                "merchant_category": profile["merchant_category"],
                "payment_method": payment_method,
                "device_type": _deterministic_choice(
                    seed + 11, ["mobile", "desktop", "tablet"]
                ),
                "location": {
                    "country": _deterministic_choice(
                        seed + 33, ["US", "CA", "UK", "BR", "JP"]
                    ),
                    "city": _deterministic_choice(
                        seed + 55,
                        ["New York", "Toronto", "London", "Sao Paulo", "Tokyo"],
                    ),
                },
                "risk_score": _deterministic_value(seed + 88, 0.0, 1.0),
            }

            events.append(event)
            event_idx += 1

    return events


def preview_labels(events: list[dict]) -> None:
    """Simulate what RuleBasedLabeling would produce and print stats."""
    import pandas as pd

    from src.feature_engineering.labeling import RuleBasedLabeling

    # Build a DataFrame with the columns labeling needs
    rows = []
    for e in events:
        ts = datetime.fromisoformat(e["timestamp"])
        rows.append(
            {
                "merchant_category": e["merchant_category"],
                "hour_of_day": ts.hour,
                "is_weekend": 1 if ts.weekday() >= 5 else 0,
                "amount": e["amount"],
            }
        )

    df = pd.DataFrame(rows)
    labeler = RuleBasedLabeling(threshold=0.65, noise_std=0.05, seed=42)
    df["label"] = labeler.assign_labels(df)

    total = len(df)
    fraud = df["label"].sum()
    legit = total - fraud

    print(f"Total events:     {total}")
    print(f"Legitimate (0):   {legit} ({legit/total*100:.1f}%)")
    print(f"Fraudulent (1):   {fraud} ({fraud/total*100:.1f}%)")
    print()

    print("By merchant category:")
    summary = (
        df.groupby("merchant_category")["label"]
        .agg(["count", "sum", "mean"])
        .rename(columns={"count": "total", "sum": "fraud", "mean": "fraud_rate"})
        .sort_values("fraud", ascending=False)
    )
    summary["fraud_rate"] = summary["fraud_rate"].map("{:.1%}".format)
    print(summary.to_string())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate deterministic demo events for reproducible demos"
    )
    parser.add_argument(
        "--output",
        default="data/sample/demo/events/demo_events.jsonl",
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview label distribution (requires pandas + labeling module)",
    )
    args = parser.parse_args()

    events = generate_events()

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    print(f"Generated {len(events)} deterministic demo events -> {output_path}")

    if args.preview:
        print()
        preview_labels(events)


if __name__ == "__main__":
    main()
