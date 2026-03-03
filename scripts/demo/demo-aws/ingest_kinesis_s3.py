#!/usr/bin/env python
import sys
import os
import argparse

# Add project root to python path
sys.path.append(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)

from src.feature_engineering.beam.pipelines import (
    FeatureEngineeringPipeline,
    create_aws_pipeline_config,
)


def main():
    parser = argparse.ArgumentParser(
        description="Run AWS Kinesis to S3 Beam Pipeline for Feature Engineering"
    )
    parser.add_argument(
        "--stream-name", type=str, required=True, help="Kinesis Data Stream name"
    )
    parser.add_argument(
        "--s3-bucket",
        type=str,
        required=True,
        help="S3 bucket for storing processed features",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="AWS Region where Kinesis and S3 exist",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default="ml-pipeline/features",
        help="Prefix for output files in S3",
    )
    parser.add_argument(
        "--runner",
        type=str,
        default="DirectRunner",
        help="Apache Beam Runner (e.g. FlinkRunner, DirectRunner)",
    )
    parser.add_argument(
        "--initial-position",
        type=str,
        default="TRIM_HORIZON",
        help="Kinesis initial position: TRIM_HORIZON (read all) or LATEST (new only)",
    )

    args = parser.parse_args()

    print(f"Starting Feature Engineering Pipeline (Runner: {args.runner})")
    print(f"Source: Kinesis stream '{args.stream_name}' in region '{args.region}'")
    print(f"Target: s3://{args.s3_bucket}/{args.output_prefix}")

    # Generate AWS pipeline config incorporating Kinesis and S3 locations
    config = create_aws_pipeline_config(
        stream_name=args.stream_name,
        region=args.region,
        s3_bucket=args.s3_bucket,
        output_prefix=args.output_prefix,
    )

    # Override runner and initial position from CLI args
    config["runner"] = args.runner
    config["input_config"]["initial_position"] = args.initial_position

    try:
        # Initialize pipeline orchestrator
        pipeline = FeatureEngineeringPipeline(config)

        # Run streaming pipeline mapping Kinesis -> Beam -> Features -> S3
        print("\nExecuting feature engineering pipeline...")
        print(f"Initial position: {args.initial_position} | Runner: {args.runner}")

        result = pipeline.run_streaming_pipeline()
        result.wait_until_finish()

    except ImportError as e:
        print(f"\n[Error] Missing dependencies: {e}")
        print("Please ensure you have installed the processing extras:")
        print("poetry install --only main,processing")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nPipeline execution cancelled by user. Shutting down gracefully...")
        # attempt to cancel if the runner supports it
        if hasattr(result, "cancel"):
            result.cancel()
    except Exception as e:
        print(f"\n[Error] Pipeline failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
