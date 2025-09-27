#!/usr/bin/env python3
"""
Load sample data into the feature store and database for demo purposes.
"""

import json
import os
import sys
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any
import pandas as pd

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

try:
    from feature_store.client import FeatureStoreClient
    from database.session import get_db_session
    from database.models import Transaction, User
except ImportError as e:
    logging.warning(f"Could not import application modules: {e}")
    logging.info("This script requires the full application to be available")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SAMPLE_DATA_DIR = "sample_data/small"

def load_json_file(filepath: str) -> List[Dict[str, Any]]:
    """Load JSON data from file."""
    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        return []

    with open(filepath, 'r') as f:
        return json.load(f)

def extract_users_from_transactions(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract unique users from transaction data."""
    users_dict = {}

    for transaction in transactions:
        user_id = transaction['user_id']
        if user_id not in users_dict:
            users_dict[user_id] = {
                'user_id': user_id,
                'first_seen': transaction['timestamp'],
                'transaction_count': 0,
                'total_amount': 0.0,
                'avg_amount': 0.0,
                'fraud_count': 0
            }

        user = users_dict[user_id]
        user['transaction_count'] += 1
        user['total_amount'] += transaction['amount']
        user['avg_amount'] = user['total_amount'] / user['transaction_count']

        if transaction['label'] == 1:
            user['fraud_count'] += 1

        # Update first_seen if this transaction is earlier
        if transaction['timestamp'] < user['first_seen']:
            user['first_seen'] = transaction['timestamp']

    return list(users_dict.values())

async def load_to_feature_store(transactions: List[Dict[str, Any]], users: List[Dict[str, Any]]) -> bool:
    """Load data to feature store."""
    try:
        # Initialize feature store client
        feature_store = FeatureStoreClient()

        logger.info("Loading user features to feature store...")

        # Load user features
        for user in users:
            user_features = {
                'user_id': user['user_id'],
                'transaction_count': user['transaction_count'],
                'avg_amount': user['avg_amount'],
                'total_amount': user['total_amount'],
                'fraud_rate': user['fraud_count'] / user['transaction_count'] if user['transaction_count'] > 0 else 0.0,
                'first_seen': user['first_seen']
            }

            await feature_store.store_features(
                entity_id=user['user_id'],
                features=user_features,
                feature_group='user_profile'
            )

        logger.info(f"Loaded {len(users)} user profiles to feature store")

        # Load transaction features
        logger.info("Loading transaction features to feature store...")

        for transaction in transactions:
            transaction_features = transaction['features'].copy()
            transaction_features.update({
                'transaction_id': transaction['transaction_id'],
                'user_id': transaction['user_id'],
                'amount': transaction['amount'],
                'merchant_category': transaction['merchant_category'],
                'payment_method': transaction['payment_method'],
                'timestamp': transaction['timestamp']
            })

            await feature_store.store_features(
                entity_id=transaction['transaction_id'],
                features=transaction_features,
                feature_group='transaction_features'
            )

        logger.info(f"Loaded {len(transactions)} transaction features to feature store")
        return True

    except Exception as e:
        logger.error(f"Failed to load data to feature store: {e}")
        return False

def load_to_database(transactions: List[Dict[str, Any]], users: List[Dict[str, Any]]) -> bool:
    """Load data to PostgreSQL database."""
    try:
        # This is a simplified version - in a real implementation,
        # you would use the actual database models and session
        logger.info("Loading data to database...")

        # Convert to DataFrames for easier handling
        df_transactions = pd.DataFrame(transactions)
        df_users = pd.DataFrame(users)

        # Save to CSV files as a fallback (can be imported to DB later)
        os.makedirs("data/demo", exist_ok=True)

        df_transactions.to_csv("data/demo/transactions.csv", index=False)
        df_users.to_csv("data/demo/users.csv", index=False)

        logger.info("Data saved to CSV files in data/demo/")
        return True

    except Exception as e:
        logger.error(f"Failed to load data to database: {e}")
        return False

def verify_data_loading() -> bool:
    """Verify that data was loaded successfully."""
    try:
        # Check if feature store is accessible
        # This would normally check the actual feature store
        logger.info("Verifying data loading...")

        # Check if CSV files were created
        required_files = [
            "data/demo/transactions.csv",
            "data/demo/users.csv"
        ]

        for file_path in required_files:
            if not os.path.exists(file_path):
                logger.error(f"Required file not found: {file_path}")
                return False

        logger.info("Data verification successful")
        return True

    except Exception as e:
        logger.error(f"Data verification failed: {e}")
        return False

async def main():
    """Main function to load sample data."""
    logger.info("🔄 Loading sample data for ML pipeline demo...")

    # Load transaction data
    transactions_file = os.path.join(SAMPLE_DATA_DIR, "sample_transactions.json")
    transactions = load_json_file(transactions_file)

    if not transactions:
        logger.error("No transaction data found. Please run 'python scripts/demo/generate_data.py' first")
        sys.exit(1)

    # Load or extract user data
    users_file = os.path.join(SAMPLE_DATA_DIR, "sample_user_features.json")
    if os.path.exists(users_file):
        users = load_json_file(users_file)
    else:
        logger.info("User features file not found, extracting from transactions...")
        users = extract_users_from_transactions(transactions)

    logger.info(f"📊 Loaded {len(transactions)} transactions and {len(users)} users")

    # Load to feature store (if available)
    try:
        feature_store_success = await load_to_feature_store(transactions, users)
    except Exception as e:
        logger.warning(f"Feature store not available: {e}")
        feature_store_success = False

    # Load to database (simplified version)
    database_success = load_to_database(transactions, users)

    # Verify loading
    verification_success = verify_data_loading()

    # Print summary
    print("\n📋 Data Loading Summary:")
    print(f"  💳 Transactions loaded: {len(transactions)}")
    print(f"  👥 Users extracted: {len(users)}")
    print(f"  🗄️  Feature store: {'✅' if feature_store_success else '❌'}")
    print(f"  💾 Database (CSV): {'✅' if database_success else '❌'}")
    print(f"  ✓ Verification: {'✅' if verification_success else '❌'}")

    # Calculate stats
    fraud_count = sum(1 for t in transactions if t['label'] == 1)
    fraud_rate = fraud_count / len(transactions) * 100

    print(f"\n📈 Dataset Statistics:")
    print(f"  🚨 Fraud transactions: {fraud_count} ({fraud_rate:.1f}%)")
    print(f"  💰 Average transaction: ${sum(t['amount'] for t in transactions) / len(transactions):.2f}")
    print(f"  🏪 Merchant categories: {len(set(t['merchant_category'] for t in transactions))}")

    if feature_store_success and database_success and verification_success:
        logger.info("✅ Sample data loaded successfully!")
        return True
    else:
        logger.error("❌ Some data loading steps failed")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)