"""AWS Kinesis Data Streams consumer implementation.

This module provides a production-ready consumer for AWS Kinesis Data Streams
that integrates with the base stream ingestion framework.
"""

import json
import time
from datetime import datetime
from typing import Dict, Any, Generator, List, Optional
import base64

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError, NoCredentialsError
except ImportError:
    boto3 = None
    ClientError = Exception
    BotoCoreError = Exception
    NoCredentialsError = Exception

from src.ingestion.base import StreamIngestion, StreamMessage, ConnectionError, MessageProcessingError
import structlog

logger = structlog.get_logger()


class KinesisConsumer(StreamIngestion):
    """AWS Kinesis Data Streams consumer implementation.

    This consumer handles message consumption from AWS Kinesis streams
    with proper shard management, error handling, and checkpointing.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize Kinesis consumer.

        Args:
            config: Configuration dictionary containing:
                - stream_name: Kinesis stream name
                - region: AWS region (default: us-east-1)
                - aws_access_key_id: AWS access key (optional, uses default credentials)
                - aws_secret_access_key: AWS secret key (optional)
                - shard_iterator_type: Type of shard iterator (default: LATEST)
                - polling_interval: Polling interval in seconds (default: 1)
                - max_records: Maximum records per GetRecords call (default: 100)

        Raises:
            ImportError: If boto3 is not installed
        """
        if boto3 is None:
            raise ImportError(
                "boto3 is required for Kinesis consumer. "
                "Install with: pip install boto3"
            )

        super().__init__(config)

        self.stream_name = config["stream_name"]
        self.region = config.get("region", "us-east-1")
        self.shard_iterator_type = config.get("shard_iterator_type", "LATEST")
        self.polling_interval = config.get("polling_interval", 1.0)
        self.max_records = config.get("max_records", 100)

        # AWS credentials (optional, will use default credential chain)
        aws_credentials = {}
        if "aws_access_key_id" in config:
            aws_credentials["aws_access_key_id"] = config["aws_access_key_id"]
        if "aws_secret_access_key" in config:
            aws_credentials["aws_secret_access_key"] = config["aws_secret_access_key"]

        self.client = None
        self.shard_iterators = {}
        self.aws_credentials = aws_credentials
        self._last_poll_time = 0

        self.logger = self.logger.bind(
            stream_name=self.stream_name,
            region=self.region,
            iterator_type=self.shard_iterator_type
        )

    def connect(self) -> None:
        """Establish connection to AWS Kinesis.

        Raises:
            ConnectionError: If connection fails
        """
        try:
            # Create Kinesis client
            self.client = boto3.client(
                'kinesis',
                region_name=self.region,
                **self.aws_credentials
            )

            # Test connection and get stream description
            stream_info = self.client.describe_stream(StreamName=self.stream_name)
            stream_status = stream_info['StreamDescription']['StreamStatus']

            if stream_status != 'ACTIVE':
                raise ConnectionError(f"Stream {self.stream_name} is not active: {stream_status}")

            # Initialize shard iterators
            self._initialize_shard_iterators(stream_info['StreamDescription']['Shards'])

            self._connected = True
            self.logger.info(
                "Connected to Kinesis stream",
                stream_status=stream_status,
                shard_count=len(self.shard_iterators)
            )

        except (ClientError, BotoCoreError, NoCredentialsError) as e:
            self._connected = False
            error_msg = f"Failed to connect to Kinesis: {str(e)}"
            self.logger.error("Kinesis connection failed", error=str(e))
            raise ConnectionError(error_msg) from e

    def consume(self, batch_size: int = 100) -> Generator[StreamMessage, None, None]:
        """Consume messages from Kinesis stream.

        Args:
            batch_size: Maximum number of records to retrieve (ignored, uses max_records)

        Yields:
            StreamMessage: Standardized stream messages

        Raises:
            MessageProcessingError: If message processing fails
        """
        if not self._connected:
            raise MessageProcessingError("Not connected to Kinesis")

        # Respect polling interval
        current_time = time.time()
        if current_time - self._last_poll_time < self.polling_interval:
            time.sleep(self.polling_interval - (current_time - self._last_poll_time))

        self._last_poll_time = time.time()

        # Process all shards
        for shard_id, iterator in list(self.shard_iterators.items()):
            if iterator is None:  # Skip exhausted iterators
                continue

            try:
                response = self.client.get_records(
                    ShardIterator=iterator,
                    Limit=min(batch_size, self.max_records)
                )

                # Update iterator for next batch
                self.shard_iterators[shard_id] = response.get('NextShardIterator')

                records = response.get('Records', [])
                self.logger.debug(
                    "Retrieved records from Kinesis shard",
                    shard_id=shard_id,
                    count=len(records)
                )

                for record in records:
                    try:
                        # Parse record data
                        message_data = self._parse_record_data(record)

                        # Create standardized message
                        stream_message = StreamMessage(
                            message_id=record['SequenceNumber'],
                            data=message_data,
                            timestamp=record['ApproximateArrivalTimestamp'],
                            source="kinesis",
                            attributes={
                                "partition_key": record.get('PartitionKey', ''),
                                "shard_id": shard_id,
                                "sequence_number": record['SequenceNumber']
                            },
                            partition_key=record.get('PartitionKey'),
                            offset=int(record['SequenceNumber'])
                        )

                        self._increment_message_count()
                        yield stream_message

                    except Exception as e:
                        self._increment_error_count()
                        self.logger.error(
                            "Failed to process Kinesis record",
                            sequence_number=record['SequenceNumber'],
                            shard_id=shard_id,
                            error=str(e)
                        )

            except (ClientError, BotoCoreError) as e:
                self._increment_error_count()
                self.logger.error(
                    "Failed to get records from Kinesis shard",
                    shard_id=shard_id,
                    error=str(e)
                )

                # Handle iterator expiration
                if "ExpiredIteratorException" in str(e):
                    self.logger.warning(
                        "Shard iterator expired, reinitializing",
                        shard_id=shard_id
                    )
                    self._reinitialize_shard_iterator(shard_id)

    def acknowledge(self, message_ids: List[str]) -> None:
        """Acknowledge processed messages.

        Args:
            message_ids: List of sequence numbers to acknowledge

        Note:
            Kinesis doesn't require explicit acknowledgment like Pub/Sub.
            This method logs the acknowledgment for monitoring purposes.
        """
        if message_ids:
            self.logger.debug(
                "Kinesis acknowledgment handled automatically",
                count=len(message_ids),
                sequence_numbers=message_ids[:10]  # Log first 10 for debugging
            )

    def close(self) -> None:
        """Close Kinesis connection and cleanup resources."""
        try:
            self._connected = False
            self.shard_iterators.clear()
            self.logger.info("Closed Kinesis connection")

        except Exception as e:
            self.logger.error("Error closing Kinesis connection", error=str(e))

    def _initialize_shard_iterators(self, shards: List[Dict[str, Any]]) -> None:
        """Initialize shard iterators for all shards.

        Args:
            shards: List of shard information from describe_stream
        """
        for shard in shards:
            shard_id = shard['ShardId']
            try:
                response = self.client.get_shard_iterator(
                    StreamName=self.stream_name,
                    ShardId=shard_id,
                    ShardIteratorType=self.shard_iterator_type
                )
                self.shard_iterators[shard_id] = response['ShardIterator']

                self.logger.debug(
                    "Initialized shard iterator",
                    shard_id=shard_id,
                    iterator_type=self.shard_iterator_type
                )

            except (ClientError, BotoCoreError) as e:
                self.logger.error(
                    "Failed to initialize shard iterator",
                    shard_id=shard_id,
                    error=str(e)
                )
                self.shard_iterators[shard_id] = None

    def _reinitialize_shard_iterator(self, shard_id: str) -> None:
        """Reinitialize a shard iterator after expiration.

        Args:
            shard_id: ID of the shard to reinitialize
        """
        try:
            response = self.client.get_shard_iterator(
                StreamName=self.stream_name,
                ShardId=shard_id,
                ShardIteratorType="LATEST"  # Use LATEST for reinitialization
            )
            self.shard_iterators[shard_id] = response['ShardIterator']

            self.logger.info(
                "Reinitialized shard iterator",
                shard_id=shard_id
            )

        except (ClientError, BotoCoreError) as e:
            self.logger.error(
                "Failed to reinitialize shard iterator",
                shard_id=shard_id,
                error=str(e)
            )
            self.shard_iterators[shard_id] = None

    def _parse_record_data(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Parse record data from Kinesis record.

        Args:
            record: Kinesis record object

        Returns:
            Parsed record data as dictionary

        Raises:
            MessageProcessingError: If parsing fails
        """
        try:
            # Kinesis data is base64 encoded
            data_bytes = record['Data']

            # Try to decode as UTF-8 string first
            try:
                data_str = data_bytes.decode('utf-8')

                # Try to parse as JSON
                try:
                    return json.loads(data_str)
                except json.JSONDecodeError:
                    # If not JSON, return as string
                    return {"raw_data": data_str}

            except UnicodeDecodeError:
                # If not UTF-8, return as base64
                return {
                    "raw_data_b64": base64.b64encode(data_bytes).decode('ascii')
                }

        except Exception as e:
            raise MessageProcessingError(f"Failed to parse Kinesis record data: {str(e)}") from e

    def get_stream_info(self) -> Dict[str, Any]:
        """Get information about the current stream.

        Returns:
            Dictionary containing stream information

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self.client:
            raise ConnectionError("Not connected to Kinesis")

        try:
            response = self.client.describe_stream(StreamName=self.stream_name)
            stream_desc = response['StreamDescription']

            return {
                "stream_name": stream_desc['StreamName'],
                "stream_status": stream_desc['StreamStatus'],
                "stream_arn": stream_desc['StreamARN'],
                "shard_count": len(stream_desc['Shards']),
                "retention_period": stream_desc['RetentionPeriodHours'],
                "stream_creation_timestamp": stream_desc['StreamCreationTimestamp'].isoformat(),
                "encryption_type": stream_desc.get('EncryptionType', 'NONE'),
                "key_id": stream_desc.get('KeyId', '')
            }

        except (ClientError, BotoCoreError) as e:
            raise ConnectionError(f"Failed to get stream info: {str(e)}") from e

    def list_shards(self) -> List[Dict[str, Any]]:
        """List all shards in the stream.

        Returns:
            List of shard information dictionaries

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self.client:
            raise ConnectionError("Not connected to Kinesis")

        try:
            response = self.client.describe_stream(StreamName=self.stream_name)
            shards = response['StreamDescription']['Shards']

            return [
                {
                    "shard_id": shard['ShardId'],
                    "parent_shard_id": shard.get('ParentShardId'),
                    "adjacent_parent_shard_id": shard.get('AdjacentParentShardId'),
                    "hash_key_range": shard['HashKeyRange'],
                    "sequence_number_range": shard['SequenceNumberRange']
                }
                for shard in shards
            ]

        except (ClientError, BotoCoreError) as e:
            raise ConnectionError(f"Failed to list shards: {str(e)}") from e