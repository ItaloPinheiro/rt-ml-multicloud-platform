"""Apache Kafka consumer implementation.

This module provides a production-ready consumer for Apache Kafka
that integrates with the base stream ingestion framework.
"""

import json
from datetime import datetime
from typing import Any, Dict, Generator, List

try:
    from confluent_kafka import Consumer, KafkaError, KafkaException
    from confluent_kafka.admin import AdminClient, ConfigResource
except ImportError:
    Consumer = None
    KafkaError = None
    KafkaException = None
    AdminClient = None
    ConfigResource = None

import structlog

from src.ingestion.base import (
    ConnectionError,
    MessageProcessingError,
    StreamIngestion,
    StreamMessage,
)

logger = structlog.get_logger()


class KafkaConsumer(StreamIngestion):
    """Apache Kafka consumer implementation.

    This consumer handles message consumption from Kafka topics
    with proper offset management, error handling, and partition assignment.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize Kafka consumer.

        Args:
            config: Configuration dictionary containing:
                - bootstrap_servers: Comma-separated list of Kafka brokers
                - topic: Kafka topic name
                - group_id: Consumer group ID
                - auto_offset_reset: Offset reset strategy (earliest/latest)
                - enable_auto_commit: Whether to auto-commit offsets (default: False)
                - session_timeout_ms: Session timeout in milliseconds (default: 30000)
                - heartbeat_interval_ms: Heartbeat interval (default: 10000)
                - max_poll_records: Maximum records per poll (default: 100)
                - poll_timeout_ms: Poll timeout in milliseconds (default: 1000)

        Raises:
            ImportError: If confluent-kafka is not installed
        """
        if Consumer is None:
            raise ImportError(
                "confluent-kafka is required for Kafka consumer. "
                "Install with: pip install confluent-kafka"
            )

        super().__init__(config)

        self.bootstrap_servers = config["bootstrap_servers"]
        self.topic = config["topic"]
        self.group_id = config["group_id"]
        self.auto_offset_reset = config.get("auto_offset_reset", "latest")
        self.enable_auto_commit = config.get("enable_auto_commit", False)
        self.session_timeout_ms = config.get("session_timeout_ms", 30000)
        self.heartbeat_interval_ms = config.get("heartbeat_interval_ms", 10000)
        self.max_poll_records = config.get("max_poll_records", 100)
        self.poll_timeout_ms = config.get("poll_timeout_ms", 1000)

        self.consumer = None
        self._pending_messages = []
        self._admin_client = None

        self.logger = self.logger.bind(
            bootstrap_servers=self.bootstrap_servers,
            topic=self.topic,
            group_id=self.group_id,
        )

    def connect(self) -> None:
        """Establish connection to Kafka cluster.

        Raises:
            ConnectionError: If connection fails
        """
        try:
            # Configure consumer
            consumer_config = {
                "bootstrap.servers": self.bootstrap_servers,
                "group.id": self.group_id,
                "auto.offset.reset": self.auto_offset_reset,
                "enable.auto.commit": self.enable_auto_commit,
                "session.timeout.ms": self.session_timeout_ms,
                "heartbeat.interval.ms": self.heartbeat_interval_ms,
                "max.poll.interval.ms": 300000,  # 5 minutes
                "api.version.request": True,
                "api.version.fallback.ms": 0,
                "client.id": f"ml-pipeline-{self.group_id}",
            }

            # Add any additional consumer configuration
            additional_config = self.config.get("consumer_config", {})
            consumer_config.update(additional_config)

            # Create consumer
            self.consumer = Consumer(consumer_config)

            # Subscribe to topic
            self.consumer.subscribe([self.topic])

            # Create admin client for metadata operations
            admin_config = {
                "bootstrap.servers": self.bootstrap_servers,
                "client.id": f"ml-pipeline-admin-{self.group_id}",
            }
            self._admin_client = AdminClient(admin_config)

            # Test connection by getting cluster metadata
            metadata = self.consumer.list_topics(timeout=10)
            if self.topic not in metadata.topics:
                raise ConnectionError(f"Topic '{self.topic}' not found in cluster")

            self._connected = True
            self.logger.info(
                "Connected to Kafka cluster",
                cluster_id=metadata.cluster_id,
                broker_count=len(metadata.brokers),
                topic_partitions=len(metadata.topics[self.topic].partitions),
            )

        except (KafkaException, Exception) as e:
            self._connected = False
            error_msg = f"Failed to connect to Kafka: {str(e)}"
            self.logger.error("Kafka connection failed", error=str(e))
            raise ConnectionError(error_msg) from e

    def consume(self, batch_size: int = 100) -> Generator[StreamMessage, None, None]:
        """Consume messages from Kafka topic.

        Args:
            batch_size: Maximum number of messages to retrieve in one batch

        Yields:
            StreamMessage: Standardized stream messages

        Raises:
            MessageProcessingError: If message processing fails
        """
        if not self._connected:
            raise MessageProcessingError("Not connected to Kafka")

        try:
            # Poll for messages
            messages_polled = 0
            poll_timeout = self.poll_timeout_ms / 1000.0  # Convert to seconds

            while messages_polled < batch_size:
                message = self.consumer.poll(timeout=poll_timeout)

                if message is None:
                    # No more messages available
                    break

                if message.error():
                    if message.error().code() == KafkaError._PARTITION_EOF:
                        # End of partition reached
                        self.logger.debug(
                            "Reached end of partition",
                            topic=message.topic(),
                            partition=message.partition(),
                            offset=message.offset(),
                        )
                        continue
                    else:
                        # Real error occurred
                        self._increment_error_count()
                        self.logger.error(
                            "Kafka message error",
                            error=message.error().str(),
                            topic=message.topic(),
                            partition=message.partition(),
                        )
                        continue

                try:
                    # Parse message data
                    message_data = self._parse_message_data(message)

                    # Create standardized message
                    stream_message = StreamMessage(
                        message_id=f"{message.topic()}-{message.partition()}-{message.offset()}",
                        data=message_data,
                        timestamp=datetime.fromtimestamp(message.timestamp()[1] / 1000),
                        source="kafka",
                        attributes={
                            "topic": message.topic(),
                            "partition": str(message.partition()),
                            "offset": str(message.offset()),
                            "key": (
                                message.key().decode("utf-8") if message.key() else None
                            ),
                            "timestamp_type": message.timestamp()[0].name,
                        },
                        partition_key=(
                            message.key().decode("utf-8") if message.key() else None
                        ),
                        offset=message.offset(),
                    )

                    # Store for manual commit if auto-commit is disabled
                    if not self.enable_auto_commit:
                        self._pending_messages.append(message)

                    self._increment_message_count()
                    messages_polled += 1
                    yield stream_message

                except Exception as e:
                    self._increment_error_count()
                    self.logger.error(
                        "Failed to process Kafka message",
                        topic=message.topic(),
                        partition=message.partition(),
                        offset=message.offset(),
                        error=str(e),
                    )

        except (KafkaException, Exception) as e:
            self._increment_error_count()
            error_msg = f"Failed to consume from Kafka: {str(e)}"
            self.logger.error("Kafka consumption failed", error=str(e))
            raise MessageProcessingError(error_msg) from e

    def acknowledge(self, message_ids: List[str]) -> None:
        """Acknowledge processed messages by committing offsets.

        Args:
            message_ids: List of message IDs to acknowledge

        Note:
            For Kafka, this commits the offsets of all pending messages.
        """
        if self.enable_auto_commit:
            self.logger.debug("Auto-commit enabled, no manual acknowledgment needed")
            return

        if not self._pending_messages:
            self.logger.debug("No messages to acknowledge")
            return

        try:
            # Commit offsets for all pending messages
            self.consumer.commit(asynchronous=False)

            self.logger.info(
                "Committed Kafka offsets", count=len(self._pending_messages)
            )

            # Clear pending messages
            self._pending_messages = []

        except (KafkaException, Exception) as e:
            self.logger.error(
                "Failed to commit Kafka offsets",
                count=len(self._pending_messages),
                error=str(e),
            )
            raise MessageProcessingError(f"Failed to commit offsets: {str(e)}") from e

    def close(self) -> None:
        """Close Kafka consumer and cleanup resources."""
        try:
            # Commit any pending offsets
            if not self.enable_auto_commit and self._pending_messages:
                self.acknowledge([])

            # Close consumer
            if self.consumer:
                self.consumer.close()

            self._connected = False
            self._pending_messages = []
            self.logger.info("Closed Kafka consumer")

        except Exception as e:
            self.logger.error("Error closing Kafka consumer", error=str(e))

    def _parse_message_data(self, message) -> Dict[str, Any]:
        """Parse message data from Kafka message.

        Args:
            message: Kafka message object

        Returns:
            Parsed message data as dictionary

        Raises:
            MessageProcessingError: If parsing fails
        """
        try:
            if message.value() is None:
                return {"raw_data": None}

            # Try to decode as UTF-8 string first
            try:
                data_str = message.value().decode("utf-8")

                # Try to parse as JSON
                try:
                    return json.loads(data_str)
                except json.JSONDecodeError:
                    # If not JSON, return as string
                    return {"raw_data": data_str}

            except UnicodeDecodeError:
                # If not UTF-8, return as base64
                import base64

                return {
                    "raw_data_b64": base64.b64encode(message.value()).decode("ascii")
                }

        except Exception as e:
            raise MessageProcessingError(
                f"Failed to parse Kafka message data: {str(e)}"
            ) from e

    def get_topic_info(self) -> Dict[str, Any]:
        """Get information about the current topic.

        Returns:
            Dictionary containing topic information

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self._admin_client:
            raise ConnectionError("Not connected to Kafka")

        try:
            metadata = self._admin_client.list_topics(topic=self.topic, timeout=10)
            topic_metadata = metadata.topics[self.topic]

            partitions = {}
            for partition_id, partition_metadata in topic_metadata.partitions.items():
                partitions[partition_id] = {
                    "id": partition_id,
                    "leader": partition_metadata.leader,
                    "replicas": partition_metadata.replicas,
                    "isrs": partition_metadata.isrs,
                    "error": (
                        partition_metadata.error.str()
                        if partition_metadata.error
                        else None
                    ),
                }

            return {
                "topic": self.topic,
                "partition_count": len(topic_metadata.partitions),
                "partitions": partitions,
                "error": topic_metadata.error.str() if topic_metadata.error else None,
            }

        except (KafkaException, Exception) as e:
            raise ConnectionError(f"Failed to get topic info: {str(e)}") from e

    def get_consumer_group_info(self) -> Dict[str, Any]:
        """Get information about the consumer group.

        Returns:
            Dictionary containing consumer group information

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self.consumer:
            raise ConnectionError("Not connected to Kafka")

        try:
            # Get current assignment
            assignment = self.consumer.assignment()

            # Get committed offsets
            committed = self.consumer.committed(assignment, timeout=10)

            # Get high water marks
            high_watermarks = (
                self.consumer.get_watermark_offsets(assignment[0])
                if assignment
                else (0, 0)
            )

            assignment_info = []
            for tp in assignment:
                committed_offset = (
                    committed[tp] if tp in committed and committed[tp] else None
                )
                assignment_info.append(
                    {
                        "topic": tp.topic,
                        "partition": tp.partition,
                        "committed_offset": (
                            committed_offset.offset if committed_offset else None
                        ),
                        "high_watermark": (
                            high_watermarks[1] if tp == assignment[0] else None
                        ),
                    }
                )

            return {
                "group_id": self.group_id,
                "assignment": assignment_info,
                "member_id": (
                    self.consumer.memberid()
                    if hasattr(self.consumer, "memberid")
                    else None
                ),
            }

        except (KafkaException, Exception) as e:
            raise ConnectionError(f"Failed to get consumer group info: {str(e)}") from e

    def seek_to_beginning(self) -> None:
        """Seek to the beginning of all assigned partitions.

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self.consumer:
            raise ConnectionError("Not connected to Kafka")

        try:
            assignment = self.consumer.assignment()
            if assignment:
                self.consumer.seek_to_beginning(assignment)
                self.logger.info("Seeked to beginning of all partitions")
            else:
                self.logger.warning("No partitions assigned, cannot seek")

        except (KafkaException, Exception) as e:
            raise ConnectionError(f"Failed to seek to beginning: {str(e)}") from e

    def seek_to_end(self) -> None:
        """Seek to the end of all assigned partitions.

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self.consumer:
            raise ConnectionError("Not connected to Kafka")

        try:
            assignment = self.consumer.assignment()
            if assignment:
                self.consumer.seek_to_end(assignment)
                self.logger.info("Seeked to end of all partitions")
            else:
                self.logger.warning("No partitions assigned, cannot seek")

        except (KafkaException, Exception) as e:
            raise ConnectionError(f"Failed to seek to end: {str(e)}") from e
