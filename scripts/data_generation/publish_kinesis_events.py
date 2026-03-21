#!/usr/bin/env python
import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import List

import boto3
import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger()

# Kinesis put_records limit: max 500 records or 5 MB per call
MAX_BATCH_SIZE = 500
MAX_BATCH_BYTES = 5 * 1024 * 1024


def generate_transaction() -> dict:
    """Generate a realistic transaction event for feature engineering.

    Timestamps are randomized across a 30-day window so Beam extracts
    diverse temporal features (hour_of_day, day_of_week, is_weekend).
    Merchant categories match the labeling heuristic in labeling.py so
    high-risk categories and interaction rules fire as expected.
    """
    random_offset = timedelta(
        days=random.randint(0, 30),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )
    timestamp = datetime.now(timezone.utc) - random_offset

    return {
        "event_id": str(uuid.uuid4()),
        "user_id": f"user_{random.randint(1, 1000)}",
        "amount": round(random.uniform(1.0, 5000.0), 2),
        "timestamp": timestamp.isoformat(),
        "merchant_category": random.choice(
            [
                "grocery",
                "gas_station",
                "restaurant",
                "pharmacy",
                "clothing",
                "online_retail",
                "electronics",
                "travel",
                "jewelry",
                "cash_advance",
            ]
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


def _build_batch(
    events_remaining: int,
) -> tuple[List[dict], List[dict]]:
    """Build a batch of Kinesis records respecting size limits.

    Returns:
        Tuple of (kinesis_records, source_events) for the batch.
    """
    records: List[dict] = []
    events: List[dict] = []
    batch_bytes = 0
    batch_count = min(events_remaining, MAX_BATCH_SIZE)

    for _ in range(batch_count):
        event = generate_transaction()
        data = json.dumps(event).encode("utf-8")
        partition_key = event["user_id"]
        # Each record overhead: partition key + data
        record_bytes = len(data) + len(partition_key.encode("utf-8"))

        if batch_bytes + record_bytes > MAX_BATCH_BYTES and records:
            break

        records.append({"Data": data, "PartitionKey": partition_key})
        events.append(event)
        batch_bytes += record_bytes

    return records, events


def _publish_batch(
    kinesis: "boto3.client",
    stream_name: str,
    records: List[dict],
    events: List[dict],
    max_retries: int = 3,
) -> int:
    """Publish a batch via put_records with retry for failed records.

    Returns:
        Number of successfully published records.
    """
    published = 0

    for attempt in range(max_retries):
        response = kinesis.put_records(
            StreamName=stream_name,
            Records=records,
        )

        failed_count = response.get("FailedRecordCount", 0)
        succeeded = len(records) - failed_count
        published += succeeded

        if failed_count == 0:
            break

        # Collect failed records for retry
        retry_records = []
        retry_events = []
        for i, result in enumerate(response["Records"]):
            if "ErrorCode" in result:
                retry_records.append(records[i])
                retry_events.append(events[i])

        logger.warning(
            "Retrying failed records",
            failed=failed_count,
            attempt=attempt + 1,
            max_retries=max_retries,
        )
        records = retry_records
        events = retry_events
        time.sleep(0.5 * (attempt + 1))

    if records and failed_count > 0:
        logger.error(
            "Some records failed after all retries",
            permanently_failed=len(records),
        )

    return published


def main() -> None:
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
        default=0,
        help="Rate limit (events/sec). 0 = unlimited (batch mode).",
    )
    parser.add_argument(
        "--total-events",
        type=int,
        default=0,
        help="Total events to publish (0 = infinite)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_BATCH_SIZE,
        help=f"Records per put_records call (max {MAX_BATCH_SIZE})",
    )

    args = parser.parse_args()
    args.batch_size = min(args.batch_size, MAX_BATCH_SIZE)

    use_batch = args.events_per_second == 0 or args.events_per_second >= 50
    mode = "batch" if use_batch else "single"

    logger.info(
        "Starting Kinesis Data Generator",
        stream_name=args.stream_name,
        region=args.region,
        mode=mode,
        rate_limit_eps=args.events_per_second if not use_batch else "unlimited",
        batch_size=args.batch_size if use_batch else 1,
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
    start_time = time.monotonic()

    try:
        if use_batch:
            _run_batch_mode(kinesis, args, events_published, start_time)
        else:
            _run_single_mode(kinesis, args, events_published, start_time)
    except KeyboardInterrupt:
        elapsed = time.monotonic() - start_time
        logger.info(
            "User interrupted. Stopping generator.",
            events_published=events_published,
            elapsed_seconds=round(elapsed, 1),
        )


def _run_batch_mode(
    kinesis: "boto3.client",
    args: argparse.Namespace,
    events_published: int,
    start_time: float,
) -> None:
    """Publish events using put_records batching."""
    total = args.total_events if args.total_events > 0 else float("inf")

    while events_published < total:
        remaining = (
            int(total - events_published) if total != float("inf") else MAX_BATCH_SIZE
        )
        records, events = _build_batch(min(remaining, args.batch_size))

        if not records:
            break

        try:
            published = _publish_batch(kinesis, args.stream_name, records, events)
            events_published += published

            logger.info(
                "Published batch",
                batch_size=len(records),
                succeeded=published,
                total_published=events_published,
            )
        except ClientError as e:
            logger.error("Failed to put batch", error=str(e))
            time.sleep(1)

    elapsed = time.monotonic() - start_time
    logger.info(
        "Reached target total events. Stopping.",
        total_events=events_published,
        elapsed_seconds=round(elapsed, 1),
        throughput_eps=round(events_published / max(elapsed, 0.001), 1),
    )


def _run_single_mode(
    kinesis: "boto3.client",
    args: argparse.Namespace,
    events_published: int,
    start_time: float,
) -> None:
    """Publish events one at a time with rate limiting."""
    sleep_interval = 1.0 / args.events_per_second if args.events_per_second > 0 else 0

    while True:
        event = generate_transaction()
        partition_key = event["user_id"]

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
                elapsed = time.monotonic() - start_time
                logger.info(
                    "Reached target total events. Stopping.",
                    total_events=args.total_events,
                    elapsed_seconds=round(elapsed, 1),
                    throughput_eps=round(events_published / max(elapsed, 0.001), 1),
                )
                break

            if sleep_interval > 0:
                time.sleep(sleep_interval)

        except ClientError as e:
            logger.error("Failed to put record", error=str(e))
            time.sleep(1)


if __name__ == "__main__":
    main()
