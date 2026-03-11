#!/usr/bin/env python3
"""
Script to inspect Feature Store contents — groups, entities, features, stats.

Usage:
  python scripts/demo/utilities/list_features.py --groups
  python scripts/demo/utilities/list_features.py --entities transaction_features
  python scripts/demo/utilities/list_features.py --features user_003 transaction_features
  python scripts/demo/utilities/list_features.py --stats transaction_features
  python scripts/demo/utilities/list_features.py --summary
"""
import argparse
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

try:
    from tabulate import tabulate

    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False


def _tabulate_or_print(rows, headers):
    """Print table using tabulate if available, else simple formatting."""
    if HAS_TABULATE:
        print(tabulate(rows, headers=headers, tablefmt="grid"))
    else:
        # Simple fallback
        header_line = " | ".join(f"{h:<25}" for h in headers)
        print(header_line)
        print("-" * len(header_line))
        for row in rows:
            print(" | ".join(f"{str(v):<25}" for v in row))


def _get_feature_store():
    """Initialize and return FeatureStore instance."""
    from src.database.session import initialize_database
    from src.feature_store.store import FeatureStore

    initialize_database()

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD")

    import redis

    try:
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=False,
            socket_timeout=5,
        )
        redis_client.ping()
    except Exception:
        redis_client = None
        print("WARNING: Redis unavailable, using PostgreSQL only")

    return FeatureStore(redis_client=redis_client)


def _get_client(store):
    """Initialize and return FeatureStoreClient."""
    from src.feature_store.client import FeatureStoreClient

    return FeatureStoreClient(feature_store=store)


def cmd_groups(store, client):
    """List all feature groups with entity/feature counts."""
    groups = store.get_feature_groups()
    if not groups:
        print("No feature groups found.")
        return

    rows = []
    for group_name in groups:
        stats = client.get_feature_statistics(group_name)
        rows.append(
            [
                group_name,
                stats.get("unique_entities", 0),
                stats.get("total_features", 0),
            ]
        )

    print(f"\nFeature Groups ({len(groups)}):")
    print("=" * 80)
    _tabulate_or_print(rows, ["Feature Group", "Entity Count", "Feature Count"])


def cmd_entities(store, group, limit):
    """List entities in a feature group."""
    from sqlalchemy import func

    from src.database.models import FeatureStore as FeatureStoreModel
    from src.database.session import get_session

    with get_session() as session:
        results = (
            session.query(
                FeatureStoreModel.entity_id,
                func.count(FeatureStoreModel.id).label("feature_count"),
                func.max(FeatureStoreModel.ingestion_timestamp).label("last_updated"),
            )
            .filter(
                FeatureStoreModel.feature_group == group,
                FeatureStoreModel.is_active.is_(True),
            )
            .group_by(FeatureStoreModel.entity_id)
            .order_by(FeatureStoreModel.entity_id)
            .limit(limit)
            .all()
        )

    if not results:
        print(f"No entities found in group '{group}'.")
        return

    rows = [[r.entity_id, r.feature_count, str(r.last_updated)[:19]] for r in results]

    print(f"\nEntities in '{group}' (showing {len(rows)}, limit={limit}):")
    print("=" * 80)
    _tabulate_or_print(rows, ["Entity ID", "Feature Count", "Last Updated"])


def cmd_features(store, entity_id, group):
    """Show features for a specific entity."""
    features = store.get_features(entity_id, group)

    if not features:
        print(f"No features found for entity '{entity_id}' in group '{group}'.")
        return

    rows = [[name, value, type(value).__name__] for name, value in features.items()]

    print(f"\nFeatures for '{entity_id}' in '{group}':")
    print("=" * 80)
    _tabulate_or_print(rows, ["Feature Name", "Value", "Data Type"])


def cmd_stats(client, group):
    """Show statistics for a feature group."""
    stats = client.get_feature_statistics(group)

    print(f"\nStatistics for '{group}':")
    print("=" * 80)
    print(f"  Unique entities: {stats.get('unique_entities', 0)}")
    print(f"  Total features:  {stats.get('total_features', 0)}")

    feature_counts = stats.get("feature_counts", {})
    if feature_counts:
        print("\n  Feature Counts:")
        rows = [[name, count] for name, count in sorted(feature_counts.items())]
        _tabulate_or_print(rows, ["Feature Name", "Count"])

    dt_dist = stats.get("data_type_distribution", {})
    if dt_dist:
        print("\n  Data Type Distribution:")
        rows = [[dtype, count] for dtype, count in sorted(dt_dist.items())]
        _tabulate_or_print(rows, ["Data Type", "Count"])


def cmd_summary(store, client):
    """Aggregate summary across all groups."""
    groups = store.get_feature_groups()
    if not groups:
        print("No feature groups found.")
        return

    total_entities = 0
    total_features = 0
    rows = []
    for group_name in groups:
        stats = client.get_feature_statistics(group_name)
        entities = stats.get("unique_entities", 0)
        features = stats.get("total_features", 0)
        total_entities += entities
        total_features += features
        rows.append([group_name, entities, features])

    print("\nFeature Store Summary:")
    print("=" * 80)
    _tabulate_or_print(rows, ["Feature Group", "Entities", "Features"])
    print(f"\n  Total groups:   {len(groups)}")
    print(f"  Total entities: {total_entities}")
    print(f"  Total features: {total_features}")


def main():
    parser = argparse.ArgumentParser(description="Inspect Feature Store contents")
    parser.add_argument("--groups", action="store_true", help="List all feature groups")
    parser.add_argument(
        "--entities",
        type=str,
        metavar="GROUP",
        help="List entities in a feature group",
    )
    parser.add_argument(
        "--features",
        nargs=2,
        metavar=("ENTITY_ID", "GROUP"),
        help="Show features for an entity in a group",
    )
    parser.add_argument(
        "--stats",
        type=str,
        metavar="GROUP",
        help="Show statistics for a feature group",
    )
    parser.add_argument("--summary", action="store_true", help="Aggregate summary")
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max entities to display (default: 50)",
    )
    parser.add_argument(
        "--redis-host",
        type=str,
        default=None,
        help="Override Redis host",
    )
    parser.add_argument(
        "--db-host",
        type=str,
        default=None,
        help="Override database host",
    )

    args = parser.parse_args()

    # Apply overrides
    if args.redis_host:
        os.environ["REDIS_HOST"] = args.redis_host
    if args.db_host:
        os.environ["DATABASE_HOST"] = args.db_host

    try:
        store = _get_feature_store()
        client = _get_client(store)

        if args.groups:
            cmd_groups(store, client)
        elif args.entities:
            cmd_entities(store, args.entities, args.limit)
        elif args.features:
            entity_id, group = args.features
            cmd_features(store, entity_id, group)
        elif args.stats:
            cmd_stats(client, args.stats)
        elif args.summary:
            cmd_summary(store, client)
        else:
            parser.print_help()

    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
