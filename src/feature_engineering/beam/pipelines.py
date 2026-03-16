"""Apache Beam feature engineering pipelines.

This module provides production-ready Apache Beam pipelines for real-time
and batch feature engineering, supporting multiple cloud platforms.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np

try:
    import apache_beam as beam
    from apache_beam.io import (
        ReadFromPubSub,
        ReadFromText,
        WriteToBigQuery,
        WriteToText,
    )
    from apache_beam.io.gcp.bigquery import BigQueryDisposition
    from apache_beam.io.kafka import ReadFromKafka, WriteToKafka

    try:
        from apache_beam.io.kinesis import InitialPositionInStream, ReadFromKinesis
    except ImportError:
        ReadFromKinesis = None
        InitialPositionInStream = None

    from apache_beam.options.pipeline_options import (
        PipelineOptions,
    )
    from apache_beam.transforms.window import FixedWindows, Sessions, SlidingWindows
except ImportError:
    beam = None
    PipelineOptions = None

import structlog

from src.feature_engineering.beam.transforms import (
    AggregateFeatures,
    FeatureExtraction,
    ValidateFeatures,
    WriteToFeatureStore,
)

logger = structlog.get_logger()


def _numpy_safe_json(obj: Any) -> str:
    """Serialize a dict to JSON, converting numpy types to Python natives."""

    def default(o: Any) -> Any:
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    return json.dumps(obj, default=default)


class FeatureEngineeringPipeline:
    """Main feature engineering pipeline orchestrator.

    This class manages the creation and execution of Apache Beam pipelines
    for real-time and batch feature engineering across multiple cloud platforms.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize feature engineering pipeline.

        Args:
            config: Pipeline configuration containing:
                - runner: Pipeline runner (DirectRunner, DataflowRunner, etc.)
                - project: GCP project ID (for cloud runners)
                - region: GCP region (for cloud runners)
                - temp_location: Temporary file location
                - staging_location: Staging file location
                - job_name: Job name for cloud runners
                - input_config: Input source configuration
                - output_config: Output destination configuration
                - feature_config: Feature extraction configuration
                - window_config: Windowing configuration
        """
        if beam is None:
            raise ImportError(
                "apache-beam is required for feature engineering pipelines. "
                "Install with: pip install apache-beam[gcp,aws]"
            )

        self.config = config
        self.logger = logger.bind(
            runner=config.get("runner", "DirectRunner"),
            project=config.get("project", "local"),
        )
        self.pipeline_options = self._create_pipeline_options()

    def _create_pipeline_options(self) -> PipelineOptions:
        """Create Apache Beam pipeline options.

        Returns:
            Configured PipelineOptions object
        """
        options = []

        # Basic options
        runner = self.config.get("runner", "DirectRunner")
        options.append(f"--runner={runner}")

        # Job naming
        job_name = self.config.get(
            "job_name", f"ml-pipeline-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        options.append(f"--job_name={job_name}")

        # Cloud-specific options
        if runner == "DataflowRunner":
            project = self.config.get("project")
            region = self.config.get("region", "us-central1")
            temp_location = self.config.get("temp_location")
            staging_location = self.config.get("staging_location")

            if project:
                options.append(f"--project={project}")
            if region:
                options.append(f"--region={region}")
            if temp_location:
                options.append(f"--temp_location={temp_location}")
            if staging_location:
                options.append(f"--staging_location={staging_location}")

            # Dataflow-specific optimizations
            options.extend(
                [
                    "--streaming",
                    "--enable_streaming_engine",
                    "--autoscaling_algorithm=THROUGHPUT_BASED",
                    f"--max_num_workers={self.config.get('max_workers', 10)}",
                    f"--num_workers={self.config.get('num_workers', 1)}",
                    "--disk_size_gb=50",
                    "--worker_machine_type=n1-standard-2",
                    "--use_public_ips=false",
                ]
            )

        elif runner == "DirectRunner":
            # Direct runner optimizations
            options.extend(
                [
                    "--direct_running_mode=multi_threading",
                    f"--direct_num_workers={self.config.get('num_workers', 4)}",
                ]
            )

        elif runner in ["FlinkRunner", "PortableRunner"]:
            # Configs for AWS Managed Service for Apache Flink / Portable runners
            temp_location = self.config.get("temp_location")
            if temp_location:
                options.append(f"--temp_location={temp_location}")
            # Flink specific parallelism
            options.extend(
                [
                    f"--parallelism={self.config.get('num_workers', 2)}",
                ]
            )

        # Additional options
        additional_options = self.config.get("pipeline_options", [])
        options.extend(additional_options)

        pipeline_options = PipelineOptions(options)

        self.logger.info(
            "Created pipeline options", runner=runner, options_count=len(options)
        )

        return pipeline_options

    def run_streaming_pipeline(self) -> "beam.pipeline.PipelineResult":
        """Run streaming feature engineering pipeline.

        Returns:
            PipelineResult object for monitoring execution
        """
        input_config = self.config.get("input_config", {})
        output_config = self.config.get("output_config", {})
        feature_config = self.config.get("feature_config", {})
        window_config = self.config.get("window_config", {})

        pipeline = beam.Pipeline(options=self.pipeline_options)

        # Read from input source
        raw_events = self._create_input_source(pipeline, input_config)

        # Feature extraction with error handling
        features_and_errors = raw_events | "ExtractFeatures" >> beam.ParDo(
            FeatureExtraction(feature_config)
        ).with_outputs("errors", main="features")

        features = features_and_errors["features"]
        extraction_errors = features_and_errors["errors"]

        # Validate features
        validated_and_invalid = features | "ValidateFeatures" >> beam.ParDo(
            ValidateFeatures(feature_config.get("validation", {}))
        ).with_outputs("invalid", "errors", main="valid")

        valid_features = validated_and_invalid["valid"]
        invalid_features = validated_and_invalid["invalid"]
        validation_errors = validated_and_invalid["errors"]

        # Apply windowing for aggregations
        windowed_features = self._apply_windowing(valid_features, window_config)

        # Aggregate features by key (e.g., user_id)
        aggregated_features = (
            windowed_features
            | "GroupByKey" >> beam.GroupBy(lambda x: x.get("user_id", "unknown"))
            | "AggregateFeatures"
            >> beam.ParDo(AggregateFeatures()).with_outputs(
                "errors", main="aggregated"
            )
        )

        final_aggregated = aggregated_features["aggregated"]
        aggregation_errors = aggregated_features["errors"]

        # Write outputs
        self._write_outputs(
            pipeline=pipeline,
            features=valid_features,
            aggregated=final_aggregated,
            errors={
                "extraction": extraction_errors,
                "validation": validation_errors,
                "aggregation": aggregation_errors,
            },
            invalid=invalid_features,
            output_config=output_config,
        )

        self.logger.info("Streaming pipeline created successfully")

        result = pipeline.run()
        result.wait_until_finish()
        return result

    def run_batch_pipeline(
        self, input_path: str, output_path: str
    ) -> "beam.pipeline.PipelineResult":
        """Run batch feature engineering pipeline.

        Args:
            input_path: Input file path or pattern
            output_path: Output file path prefix

        Returns:
            PipelineResult object for monitoring execution
        """
        feature_config = self.config.get("feature_config", {})

        with beam.Pipeline(options=self.pipeline_options) as pipeline:
            # Read from input files
            raw_data = (
                pipeline
                | "ReadFromFiles" >> ReadFromText(input_path)
                | "ParseJSON" >> beam.Map(self._parse_json_safely)
                | "FilterValid"
                >> beam.Filter(lambda x: x is not None).with_output_types(
                    Dict[str, Any]
                )
            )

            # Extract features
            features = (
                raw_data
                | "ExtractFeatures" >> beam.ParDo(FeatureExtraction(feature_config))
                | "FilterFeatures"
                >> beam.Filter(
                    lambda x: not isinstance(x, dict) or x.get("error") is None
                )
            )

            # Write features to output
            features | "WriteFeatures" >> WriteToText(
                file_path_prefix=f"{output_path}/features",
                file_name_suffix=".json",
                shard_name_template="-SS-of-NN",
            )

            self.logger.info(
                "Batch pipeline created successfully",
                input_path=input_path,
                output_path=output_path,
            )

        return pipeline.run().wait_until_finish()

    def _create_input_source(
        self, pipeline: "beam.Pipeline", input_config: Dict[str, Any]
    ):
        """Create input source based on configuration.

        Args:
            pipeline: Beam pipeline object
            input_config: Input configuration

        Returns:
            PCollection of input data
        """
        source_type = input_config.get("type", "pubsub")

        if source_type == "pubsub":
            topic = input_config.get("topic")
            subscription = input_config.get("subscription")

            if subscription:
                return (
                    pipeline
                    | "ReadFromPubSub" >> ReadFromPubSub(subscription=subscription)
                    | "DecodeMessages" >> beam.Map(lambda x: x.decode("utf-8"))
                    | "ParsePubSubJSON" >> beam.Map(self._parse_json_safely)
                    | "FilterPubSubNulls"
                    >> beam.Filter(lambda x: x is not None).with_output_types(
                        Dict[str, Any]
                    )
                )
            elif topic:
                return (
                    pipeline
                    | "ReadFromPubSubTopic" >> ReadFromPubSub(topic=topic)
                    | "DecodeTopicMessages" >> beam.Map(lambda x: x.decode("utf-8"))
                    | "ParseTopicJSON" >> beam.Map(self._parse_json_safely)
                    | "FilterTopicNulls"
                    >> beam.Filter(lambda x: x is not None).with_output_types(
                        Dict[str, Any]
                    )
                )
            else:
                raise ValueError(
                    "PubSub input requires either 'subscription' or 'topic' in config"
                )

        elif source_type == "kafka":
            bootstrap_servers = input_config.get("bootstrap_servers")
            topics = input_config.get("topics", [])

            return (
                pipeline
                | "ReadFromKafka"
                >> ReadFromKafka(
                    consumer_config={
                        "bootstrap.servers": bootstrap_servers,
                        "group.id": input_config.get("group_id", "ml-pipeline"),
                        "auto.offset.reset": input_config.get(
                            "auto_offset_reset", "latest"
                        ),
                    },
                    topics=topics,
                )
                | "ExtractKafkaValue"
                >> beam.Map(lambda record: record[1].decode("utf-8"))
                | "ParseKafkaJSON" >> beam.Map(self._parse_json_safely)
                | "FilterKafkaNulls"
                >> beam.Filter(lambda x: x is not None).with_output_types(
                    Dict[str, Any]
                )
            )

        elif source_type == "kinesis":
            stream_name = input_config.get("stream_name")
            region = input_config.get("region", "us-east-1")
            initial_pos = input_config.get("initial_position", "LATEST")

            if ReadFromKinesis is not None:
                # Cross-language transform (requires FlinkRunner/SparkRunner)
                aws_access_key = input_config.get("aws_access_key", "")
                aws_secret_key = input_config.get("aws_secret_key", "")

                position = InitialPositionInStream.LATEST
                if initial_pos == "TRIM_HORIZON":
                    position = InitialPositionInStream.TRIM_HORIZON
                elif initial_pos == "AT_TIMESTAMP":
                    position = InitialPositionInStream.AT_TIMESTAMP

                return (
                    pipeline
                    | "ReadFromKinesis"
                    >> ReadFromKinesis(
                        stream_name=stream_name,
                        aws_access_key=aws_access_key,
                        aws_secret_key=aws_secret_key,
                        region=region,
                        initial_position_in_stream=position,
                    )
                    | "ExtractKinesisValue"
                    >> beam.Map(
                        lambda record: (
                            record.data if hasattr(record, "data") else record
                        ).decode("utf-8")
                    )
                    | "ParseKinesisJSON" >> beam.Map(self._parse_json_safely)
                    | "FilterKinesisNulls"
                    >> beam.Filter(lambda x: x is not None).with_output_types(
                        Dict[str, Any]
                    )
                )
            else:
                # Fallback: boto3-based reader for DirectRunner
                self.logger.info(
                    "ReadFromKinesis not available, using boto3 fallback",
                    stream=stream_name,
                    region=region,
                    position=initial_pos,
                )
                records = _read_kinesis_via_boto3(stream_name, region, initial_pos)
                self.logger.info(
                    "Read records from Kinesis via boto3",
                    count=len(records),
                )
                return (
                    pipeline
                    | "CreateFromKinesis" >> beam.Create(records)
                    | "ParseKinesisJSON" >> beam.Map(self._parse_json_safely)
                    | "FilterNulls"
                    >> beam.Filter(lambda x: x is not None).with_output_types(
                        Dict[str, Any]
                    )
                )

        elif source_type == "file":
            file_pattern = input_config.get("file_pattern")
            return (
                pipeline
                | "ReadFromFile" >> ReadFromText(file_pattern)
                | "ParseFileJSON" >> beam.Map(self._parse_json_safely)
                | "FilterFileNulls"
                >> beam.Filter(lambda x: x is not None).with_output_types(
                    Dict[str, Any]
                )
            )

        else:
            raise ValueError(f"Unsupported input source type: {source_type}")

    def _apply_windowing(self, pcollection, window_config: Dict[str, Any]):
        """Apply windowing to PCollection.

        Args:
            pcollection: Input PCollection
            window_config: Windowing configuration

        Returns:
            Windowed PCollection
        """
        window_type = window_config.get("type", "fixed")
        window_size = window_config.get("size_seconds", 60)

        if window_type == "fixed":
            return pcollection | "FixedWindows" >> beam.WindowInto(
                FixedWindows(window_size)
            )

        elif window_type == "sliding":
            slide_period = window_config.get("slide_seconds", 30)
            return pcollection | "SlidingWindows" >> beam.WindowInto(
                SlidingWindows(window_size, slide_period)
            )

        elif window_type == "session":
            gap_size = window_config.get("gap_seconds", 600)
            return pcollection | "SessionWindows" >> beam.WindowInto(Sessions(gap_size))

        else:
            # No windowing
            return pcollection

    def _write_outputs(
        self,
        pipeline: "beam.Pipeline",
        features,
        aggregated,
        errors: Dict[str, Any],
        invalid,
        output_config: Dict[str, Any],
    ):
        """Write pipeline outputs to configured destinations.

        Args:
            pipeline: Beam pipeline object
            features: Individual features PCollection
            aggregated: Aggregated features PCollection
            errors: Error PCollections dictionary
            invalid: Invalid features PCollection
            output_config: Output configuration
        """
        output_type = output_config.get("type", "bigquery")

        if output_type == "bigquery":
            project = output_config.get("project")
            dataset = output_config.get("dataset", "ml_pipeline")

            # Write features
            features | "WriteFeaturesToBQ" >> WriteToBigQuery(
                table=f"{project}:{dataset}.features",
                schema="SCHEMA_AUTODETECT",
                write_disposition=BigQueryDisposition.WRITE_APPEND,
                create_disposition=BigQueryDisposition.CREATE_IF_NEEDED,
            )

            # Write aggregated features
            aggregated | "WriteAggregatedToBQ" >> WriteToBigQuery(
                table=f"{project}:{dataset}.aggregated_features",
                schema="SCHEMA_AUTODETECT",
                write_disposition=BigQueryDisposition.WRITE_APPEND,
                create_disposition=BigQueryDisposition.CREATE_IF_NEEDED,
            )

            # Write errors
            all_errors = (
                errors["extraction"],
                errors["validation"],
                errors["aggregation"],
            ) | "FlattenErrors" >> beam.Flatten()

            all_errors | "WriteErrorsToBQ" >> WriteToBigQuery(
                table=f"{project}:{dataset}.errors",
                schema="SCHEMA_AUTODETECT",
                write_disposition=BigQueryDisposition.WRITE_APPEND,
                create_disposition=BigQueryDisposition.CREATE_IF_NEEDED,
            )

            # Write invalid features
            invalid | "WriteInvalidToBQ" >> WriteToBigQuery(
                table=f"{project}:{dataset}.invalid_features",
                schema="SCHEMA_AUTODETECT",
                write_disposition=BigQueryDisposition.WRITE_APPEND,
                create_disposition=BigQueryDisposition.CREATE_IF_NEEDED,
            )

        elif output_type == "file":
            output_path = output_config.get("path", "/tmp/pipeline_output")

            # Write features
            (
                features
                | "SerializeFeaturesForFile" >> beam.Map(_numpy_safe_json)
                | "WriteFeaturesToFile"
                >> WriteToText(
                    file_path_prefix=f"{output_path}/features",
                    file_name_suffix=".json",
                )
            )

            # Write aggregated features
            (
                aggregated
                | "SerializeAggregatedForFile" >> beam.Map(_numpy_safe_json)
                | "WriteAggregatedToFile"
                >> WriteToText(
                    file_path_prefix=f"{output_path}/aggregated",
                    file_name_suffix=".json",
                )
            )

        elif output_type == "s3":
            # Using WriteToText which inherently supports s3:// prefixes when apache-beam[aws] is available
            output_path = output_config.get("path")
            if not output_path or not output_path.startswith("s3://"):
                raise ValueError("S3 output type requires a path starting with s3://")

            # Write features
            (
                features
                | "SerializeFeaturesForS3" >> beam.Map(_numpy_safe_json)
                | "WriteFeaturesToS3"
                >> WriteToText(
                    file_path_prefix=f"{output_path}/features",
                    file_name_suffix=".json",
                )
            )

            # Write aggregated features
            (
                aggregated
                | "SerializeAggregatedForS3" >> beam.Map(_numpy_safe_json)
                | "WriteAggregatedToS3"
                >> WriteToText(
                    file_path_prefix=f"{output_path}/aggregated",
                    file_name_suffix=".json",
                )
            )

        elif output_type == "kafka":
            bootstrap_servers = output_config.get("bootstrap_servers")

            # Write features to Kafka
            (
                features
                | "FormatFeaturesForKafka"
                >> beam.Map(lambda x: (None, json.dumps(x).encode("utf-8")))
                | "WriteFeaturesToKafka"
                >> WriteToKafka(
                    producer_config={"bootstrap.servers": bootstrap_servers},
                    topic=output_config.get("features_topic", "ml-features"),
                )
            )

            # Write aggregated features to Kafka
            (
                aggregated
                | "FormatAggregatedForKafka"
                >> beam.Map(lambda x: (None, json.dumps(x).encode("utf-8")))
                | "WriteAggregatedToKafka"
                >> WriteToKafka(
                    producer_config={"bootstrap.servers": bootstrap_servers},
                    topic=output_config.get("aggregated_topic", "ml-aggregated"),
                )
            )

        elif output_type in ("feature_store", "s3+feature_store"):
            fs_config = output_config.get("feature_store", {})
            fs_kwargs = {
                "redis_host": fs_config.get("redis_host", "localhost"),
                "redis_port": fs_config.get("redis_port", 6379),
                "redis_password": fs_config.get("redis_password"),
                "db_host": fs_config.get("db_host"),
                "db_port": fs_config.get("db_port"),
                "db_name": fs_config.get("db_name"),
                "entity_key_field": fs_config.get("entity_key_field", "user_id"),
                "ttl_seconds": fs_config.get("ttl_seconds", 86400),
                "write_batch_size": fs_config.get("write_batch_size", 100),
            }

            # Write per-record features to feature store
            features | "WriteFeaturesToFeatureStore" >> beam.ParDo(
                WriteToFeatureStore(
                    feature_group=fs_config.get(
                        "feature_group", "transaction_features"
                    ),
                    **fs_kwargs,
                )
            ).with_outputs("dead_letter", main="written")

            # Write aggregated features to feature store
            aggregated | "WriteAggregatedToFeatureStore" >> beam.ParDo(
                WriteToFeatureStore(
                    feature_group=fs_config.get(
                        "aggregated_feature_group", "aggregated_features"
                    ),
                    **fs_kwargs,
                )
            ).with_outputs("dead_letter", main="written")

            # Dual-write: also write to S3 when output_type is s3+feature_store
            if output_type == "s3+feature_store":
                s3_path = output_config.get("path")
                if s3_path:
                    (
                        features
                        | "SerializeFeaturesForS3FS" >> beam.Map(_numpy_safe_json)
                        | "WriteFeaturesToS3FS"
                        >> WriteToText(
                            file_path_prefix=f"{s3_path}/features",
                            file_name_suffix=".json",
                        )
                    )
                    (
                        aggregated
                        | "SerializeAggregatedForS3FS" >> beam.Map(_numpy_safe_json)
                        | "WriteAggregatedToS3FS"
                        >> WriteToText(
                            file_path_prefix=f"{s3_path}/aggregated",
                            file_name_suffix=".json",
                        )
                    )

    def _parse_json_safely(self, json_string: str) -> Optional[Dict[str, Any]]:
        """Safely parse JSON string.

        Args:
            json_string: JSON string to parse

        Returns:
            Parsed dictionary or None if parsing fails
        """
        try:
            return json.loads(json_string)
        except (json.JSONDecodeError, TypeError, ValueError):
            self.logger.warning("Failed to parse JSON", data=json_string[:100])
            return None

    def create_test_data_pipeline(
        self, output_path: str, num_records: int = 1000
    ) -> "beam.pipeline.PipelineResult":
        """Create a pipeline that generates test data for development.

        Args:
            output_path: Path to write test data
            num_records: Number of test records to generate

        Returns:
            PipelineResult object
        """
        import random

        def generate_test_record(index):
            """Generate a test record."""
            return {
                "user_id": f"user_{random.randint(1, 100)}",
                "amount": round(random.uniform(10, 1000), 2),
                "merchant_category": random.choice(
                    ["grocery", "gas", "restaurant", "retail", "online"]
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payment_method": random.choice(["credit", "debit", "cash", "mobile"]),
                "is_weekend": random.choice([True, False]),
                "risk_score": round(random.uniform(0, 1), 3),
                "account_age_days": random.randint(1, 3650),
            }

        with beam.Pipeline(options=self.pipeline_options) as pipeline:
            test_data = (
                pipeline
                | "CreateIndices" >> beam.Create(range(num_records))
                | "GenerateTestData" >> beam.Map(generate_test_record)
                | "ConvertToJSON" >> beam.Map(json.dumps)
            )

            test_data | "WriteTestData" >> WriteToText(
                file_path_prefix=output_path, file_name_suffix=".json"
            )

            self.logger.info(
                "Test data pipeline created",
                output_path=output_path,
                num_records=num_records,
            )

        return pipeline.run()


def _read_kinesis_via_boto3(
    stream_name: str, region: str, initial_position: str = "TRIM_HORIZON"
) -> list:
    """Read all records from a Kinesis stream using boto3.

    This is a bounded fallback for DirectRunner when the cross-language
    ReadFromKinesis transform is not available. Iterates all shards and
    reads records until each shard is exhausted.

    Args:
        stream_name: Kinesis Data Stream name
        region: AWS region
        initial_position: TRIM_HORIZON (all records) or LATEST (new only)

    Returns:
        List of decoded record data strings (JSON)
    """
    import boto3

    client = boto3.client("kinesis", region_name=region)

    # Get all shard IDs
    shards = []
    paginator = client.get_paginator("list_shards")
    for page in paginator.paginate(StreamName=stream_name):
        shards.extend(page["Shards"])

    shard_iterator_type = (
        "TRIM_HORIZON" if initial_position == "TRIM_HORIZON" else "LATEST"
    )

    records_out = []
    for shard in shards:
        shard_id = shard["ShardId"]
        iterator_resp = client.get_shard_iterator(
            StreamName=stream_name,
            ShardId=shard_id,
            ShardIteratorType=shard_iterator_type,
        )
        shard_iterator = iterator_resp["ShardIterator"]

        # Read until the shard is exhausted (no more records and iterator stops advancing)
        empty_responses = 0
        while shard_iterator and empty_responses < 3:
            resp = client.get_records(ShardIterator=shard_iterator, Limit=1000)
            batch = resp.get("Records", [])

            if not batch:
                empty_responses += 1
            else:
                empty_responses = 0
                for record in batch:
                    records_out.append(record["Data"].decode("utf-8"))

            shard_iterator = resp.get("NextShardIterator")

    return records_out


def create_dataflow_pipeline_config(
    project: str, region: str, bucket: str, input_subscription: str, output_dataset: str
) -> Dict[str, Any]:
    """Create a standard Dataflow pipeline configuration.

    Args:
        project: GCP project ID
        region: GCP region
        bucket: GCS bucket for temp and staging
        input_subscription: Pub/Sub subscription name
        output_dataset: BigQuery dataset name

    Returns:
        Pipeline configuration dictionary
    """
    return {
        "runner": "DataflowRunner",
        "project": project,
        "region": region,
        "temp_location": f"gs://{bucket}/temp",
        "staging_location": f"gs://{bucket}/staging",
        "max_workers": 10,
        "num_workers": 2,
        "input_config": {
            "type": "pubsub",
            "subscription": f"projects/{project}/subscriptions/{input_subscription}",
        },
        "output_config": {
            "type": "bigquery",
            "project": project,
            "dataset": output_dataset,
        },
        "window_config": {"type": "fixed", "size_seconds": 60},
        "feature_config": {
            "validation": {
                "required_fields": ["user_id", "amount", "timestamp"],
                "numeric_ranges": {"amount": [0, 100000], "risk_score": [0, 1]},
            }
        },
    }


def create_local_pipeline_config(input_file: str, output_path: str) -> Dict[str, Any]:
    """Create a local development pipeline configuration.

    Args:
        input_file: Local input file path
        output_path: Local output directory path

    Returns:
        Pipeline configuration dictionary
    """
    return {
        "runner": "DirectRunner",
        "num_workers": 4,
        "input_config": {"type": "file", "file_pattern": input_file},
        "output_config": {"type": "file", "path": output_path},
        "feature_config": {
            "validation": {
                "required_fields": ["user_id", "amount"],
                "numeric_ranges": {"amount": [0, 10000]},
            }
        },
    }


def create_aws_pipeline_config(
    stream_name: str, region: str, s3_bucket: str, output_prefix: str
) -> Dict[str, Any]:
    """Create a standard AWS Kinesis to S3 pipeline configuration.

    Args:
        stream_name: Kinesis stream name
        region: AWS region
        s3_bucket: S3 bucket for temp and staging
        output_prefix: Output prefix in S3

    Returns:
        Pipeline configuration dictionary
    """
    return {
        "runner": "DirectRunner",
        "region": region,
        "temp_location": f"s3://{s3_bucket}/temp",
        "staging_location": f"s3://{s3_bucket}/staging",
        "num_workers": 2,
        "input_config": {
            "type": "kinesis",
            "stream_name": stream_name,
            "region": region,
            "initial_position": "TRIM_HORIZON",
        },
        "output_config": {
            "type": "s3+feature_store",
            "path": f"s3://{s3_bucket}/{output_prefix}",
            "feature_store": {
                "redis_host": os.getenv("REDIS_HOST", "redis-service"),
                "redis_port": int(os.getenv("REDIS_PORT", "6379")),
                "redis_password": os.getenv("REDIS_PASSWORD"),
                "entity_key_field": "user_id",
                "ttl_seconds": int(os.getenv("FEATURE_STORE_TTL", "86400")),
                "write_batch_size": 100,
            },
        },
        "window_config": {"type": "fixed", "size_seconds": 60},
        "feature_config": {
            "validation": {
                "required_fields": ["user_id", "amount", "timestamp"],
                "numeric_ranges": {"amount": [0, 100000], "risk_score": [0, 1]},
            }
        },
    }
