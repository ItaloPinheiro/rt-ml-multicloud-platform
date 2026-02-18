#!/usr/bin/env python3
"""
Generate sample data for ML pipeline demo.
This script creates transaction data and user features for demo purposes.
"""

import json
import os
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd

# Configuration
DATA_ROOT = os.getenv("DATA_ROOT", "data/sample")
GENERATED_DIR = os.path.join(DATA_ROOT, "generated")
DEMO_DIR = os.path.join(DATA_ROOT, "demo")
DEMO_DATASETS_DIR = os.path.join(DEMO_DIR, "datasets")
DEMO_REQUESTS_DIR = os.path.join(DEMO_DIR, "requests")
NUM_TRANSACTIONS = 1000
NUM_USERS = 100
FRAUD_RATE = 0.05  # 5% of transactions are fraudulent

# Merchant categories with fraud likelihood
MERCHANT_CATEGORIES = {
    "grocery": 0.01,
    "gas_station": 0.02,
    "restaurant": 0.03,
    "electronics": 0.08,
    "jewelry": 0.15,
    "cash_advance": 0.25,
    "online_retail": 0.06,
    "pharmacy": 0.01,
    "clothing": 0.04,
    "travel": 0.10,
}

CITIES = [
    ("New York", "NY", "10001"),
    ("Los Angeles", "CA", "90210"),
    ("Chicago", "IL", "60601"),
    ("Houston", "TX", "77001"),
    ("Phoenix", "AZ", "85001"),
    ("Philadelphia", "PA", "19101"),
    ("San Antonio", "TX", "78201"),
    ("San Diego", "CA", "92101"),
    ("Dallas", "TX", "75201"),
    ("San Jose", "CA", "95101"),
]


def generate_user_features() -> List[Dict[str, Any]]:
    """Generate user feature data."""
    users = []

    for i in range(NUM_USERS):
        user = {
            "user_id": f"user_{i:03d}",
            "demographics": {
                "age": random.randint(18, 80),
                "income": random.randint(25000, 150000),
                "credit_score": random.randint(300, 850),
                "account_age_months": random.randint(1, 120),
            },
            "location": {
                "city": random.choice(CITIES)[0],
                "state": random.choice(CITIES)[1],
                "country": "US",
                "zip_code": random.choice(CITIES)[2],
            },
            "behavior": {
                "avg_monthly_transactions": random.randint(5, 50),
                "preferred_categories": random.sample(
                    list(MERCHANT_CATEGORIES.keys()), 3
                ),
                "typical_amount_range": [
                    round(random.uniform(10, 100), 2),
                    round(random.uniform(100, 1000), 2),
                ],
                "active_hours": list(
                    range(random.randint(6, 9), random.randint(18, 23))
                ),
            },
            "risk_profile": {
                "historical_fraud_reports": random.randint(0, 2),
                "suspicious_activity_flags": random.randint(0, 3),
                "risk_score": round(random.uniform(0.0, 1.0), 3),
            },
        }
        users.append(user)

    return users


def generate_transactions(users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate transaction data based on user profiles."""
    transactions = []
    base_time = datetime.now() - timedelta(days=30)

    for i in range(NUM_TRANSACTIONS):
        user = random.choice(users)
        merchant_category = random.choice(list(MERCHANT_CATEGORIES.keys()))

        # Generate timestamp
        timestamp = base_time + timedelta(
            days=random.randint(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        # Generate amount based on category and user profile
        if merchant_category in ["jewelry", "electronics", "travel"]:
            amount = round(random.uniform(200, 3000), 2)
        elif merchant_category in ["cash_advance"]:
            amount = round(random.uniform(500, 5000), 2)
        else:
            amount = round(random.uniform(5, 500), 2)

        # Calculate features
        hour_of_day = timestamp.hour
        day_of_week = timestamp.weekday()
        is_weekend = day_of_week >= 5

        # Risk score calculation
        risk_factors = 0
        if hour_of_day < 6 or hour_of_day > 22:
            risk_factors += 0.2
        if amount > 1000:
            risk_factors += 0.3
        if merchant_category in ["jewelry", "cash_advance"]:
            risk_factors += 0.4
        if is_weekend and merchant_category == "cash_advance":
            risk_factors += 0.3

        risk_score = min(risk_factors + user["risk_profile"]["risk_score"], 1.0)

        # Determine if fraudulent
        fraud_probability = MERCHANT_CATEGORIES[merchant_category] + risk_factors
        is_fraud = random.random() < fraud_probability and random.random() < FRAUD_RATE

        # Generate city info
        city, state, zip_code = random.choice(CITIES)

        transaction = {
            "transaction_id": f"txn_{i:06d}",
            "user_id": user["user_id"],
            "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "amount": amount,
            "merchant_id": f"merchant_{random.randint(1000, 9999)}",
            "merchant_category": merchant_category,
            "payment_method": random.choice(["credit", "debit", "mobile", "online"]),
            "location": {
                "city": city,
                "state": state,
                "country": "US",
                "zip_code": zip_code,
            },
            "device_info": {
                "device_id": f"device_{random.randint(100, 999)}",
                "ip_address": f"{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}",
                "user_agent": random.choice(
                    [
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "Mobile App v2.1",
                        "Chrome/91.0",
                        "Safari/537.36",
                    ]
                ),
            },
            "features": {
                "hour_of_day": hour_of_day,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "transaction_count_24h": random.randint(1, 10),
                "avg_amount_30d": round(random.uniform(50, 300), 2),
                "risk_score": round(risk_score, 3),
            },
            "label": 1 if is_fraud else 0,
        }

        transactions.append(transaction)

    return transactions


def create_sample_request_file(transactions: List[Dict[str, Any]]) -> None:
    """Create a sample request file for API testing."""
    sample_transaction = random.choice(transactions)

    # Prepare features matching training data
    features = sample_transaction["features"].copy()
    features["amount"] = sample_transaction["amount"]
    features["merchant_category_encoded"] = (
        hash(sample_transaction["merchant_category"]) % 100
    )
    features["payment_method_encoded"] = hash(sample_transaction["payment_method"]) % 10

    sample_request = {
        "features": features,
        "model_name": "fraud_detector",
        "return_probabilities": True,
    }

    # Ensure directories exist
    os.makedirs(DEMO_REQUESTS_DIR, exist_ok=True)

    # Save baseline request
    with open(
        os.path.join(DEMO_REQUESTS_DIR, "baseline_prediction_request.json"), "w"
    ) as f:
        json.dump(sample_request, f, indent=2)


def main():
    """Generate all sample data files."""
    print("Generating sample data for ML pipeline demo...")

    # Ensure all directories exist
    os.makedirs(GENERATED_DIR, exist_ok=True)
    os.makedirs(DEMO_DATASETS_DIR, exist_ok=True)
    os.makedirs(DEMO_REQUESTS_DIR, exist_ok=True)

    # Generate user features
    print(f"Generating {NUM_USERS} user profiles...")
    users = generate_user_features()

    with open(os.path.join(GENERATED_DIR, "user_features.json"), "w") as f:
        json.dump(users, f, indent=2)

    # Generate transactions
    print(f"Generating {NUM_TRANSACTIONS} transactions...")
    transactions = generate_transactions(users)

    with open(os.path.join(GENERATED_DIR, "transactions.json"), "w") as f:
        json.dump(transactions, f, indent=2)

    # Create sample request file
    create_sample_request_file(transactions)

    # Generate training data CSV for model training
    print("Creating training dataset...")
    df_transactions = pd.DataFrame(transactions)

    # Flatten features for training
    feature_columns = []
    for _, row in df_transactions.iterrows():
        features = row["features"].copy()
        features["amount"] = row["amount"]
        features["merchant_category_encoded"] = hash(row["merchant_category"]) % 100
        features["payment_method_encoded"] = hash(row["payment_method"]) % 10
        features["label"] = row["label"]
        feature_columns.append(features)

    df_features = pd.DataFrame(feature_columns)
    df_features.to_csv(
        os.path.join(DEMO_DATASETS_DIR, "fraud_detection.csv"), index=False
    )

    # Print statistics
    fraud_count = sum(1 for t in transactions if t["label"] == 1)
    print("Sample data generation complete!")
    print(f"   Total transactions: {len(transactions)}")
    print(f"   Total users: {len(users)}")
    print(
        f"   Fraudulent transactions: {fraud_count} ({fraud_count/len(transactions)*100:.1f}%)"
    )
    print(f"   Generated files saved to: {GENERATED_DIR}/")
    print(f"   Training data: {DEMO_DATASETS_DIR}/fraud_detection.csv")
    print(f"   API requests: {DEMO_REQUESTS_DIR}/")


if __name__ == "__main__":
    main()
