#!/usr/bin/env python
import argparse
import json
import time
import random
import uuid
from datetime import datetime, timezone
import structlog
import boto3
from botocore.exceptions import ClientError

logger = structlog.get_logger()


def generate_transaction() -> dict:
    """Generate a realistic transaction event for feature engineering."""
    return {
        "event_id": str(uuid.uuid4()),
        "user_id": f"user_{random.randint(1, 1000)}",
        "amount": round(random.uniform(1.0, 5000.0), 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "merchant_category": random.choice(
            ["retail", "travel", "food", "entertainment", "utilities"]
        ),
        "payment_method": random.choice(
            ["credit_card", "debit_card", "digital_wallet", "bank_transfer"]
        ),
        "device_type": random.choice(["mobile", "desktop", "tablet"]),
        "location": {
            "country": random.choice(["US", "CA", "UK", "BR", "JP"]),
            "city": random.choice(
                ["New York", "Toronto", "London", "São Paulo", "Tokyo"]
            ),
        },
        "risk_score": round(random.uniform(0.0, 1.0), 3),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Publish mock transaction events to an AWS Kinesis Data Stream"
    )
    parser.add_argument(
        "--stream-name", required=True, help="Target Kinesis Data Stream name"
    )
    parser.add_argument("--region", default="us-east-1", help="AWS Region")
    parser.add_argument(
        "--events-per-second",
        type=float,
        default=2.0,
        help="Number of events to publish per second",
    )
    parser.add_argument(
        "--total-events",
        type=int,
        default=0,
        help="Total events to publish (0 = infinite)",
    )

    args = parser.parse_args()

    logger.info(
        "Starting Kinesis Data Generator",
        stream_name=args.stream_name,
        region=args.region,
        rate_limit_eps=args.events_per_second,
    )

    kinesis = boto3.client("kinesis", region_name=args.region)

    # Verify stream exists and is active
    try:
        response = kinesis.describe_stream(StreamName=args.stream_name)
        status = response["StreamDescription"]["StreamStatus"]
        if status != "ACTIVE":
            logger.error("Kinesis stream is not ACTIVE", current_status=status)
            return
    except ClientError as e:
        logger.error(
            "Failed to describe stream. Ensure it exists and credentials are valid",
            error=str(e),
        )
        return

    events_published = 0
    sleep_interval = 1.0 / args.events_per_second if args.events_per_second > 0 else 0

    try:
        while True:
            event = generate_transaction()
            partition_key = event[
                "user_id"
            ]  # ensure events for the same user go to the same shard

            try:
                response = kinesis.put_record(
                    StreamName=args.stream_name,
                    Data=json.dumps(event).encode("utf-8"),
                    PartitionKey=partition_key,
                )
                logger.info(
                    "Published event",
                    event_id=event["event_id"],
                    shard_id=response["ShardId"],
                    seq_number=response["SequenceNumber"],
                )
                events_published += 1

                if args.total_events > 0 and events_published >= args.total_events:
                    logger.info(
                        "Reached target total events. Stopping.",
                        total_events=args.total_events,
                    )
                    break

                if sleep_interval > 0:
                    time.sleep(sleep_interval)

            except ClientError as e:
                logger.error("Failed to put record", error=str(e))
                time.sleep(1)  # Backoff

    except KeyboardInterrupt:
        logger.info(
            "\nUser interrupted. Stopping generator.", events_published=events_published
        )


if __name__ == "__main__":
    main()
