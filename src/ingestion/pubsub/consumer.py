"""Google Cloud Pub/Sub consumer implementation.

This module provides a production-ready consumer for Google Cloud Pub/Sub
that integrates with the base stream ingestion framework.
"""

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from typing import Any, Dict, Generator, List

try:
    from google.api_core import retry
    from google.api_core.exceptions import DeadlineExceeded, GoogleAPIError
    from google.cloud import pubsub_v1
except ImportError:
    pubsub_v1 = None
    retry = None
    GoogleAPIError = Exception
    DeadlineExceeded = Exception

import structlog

from src.ingestion.base import (
    ConnectionError,
    MessageProcessingError,
    StreamIngestion,
    StreamMessage,
)

logger = structlog.get_logger()


class PubSubConsumer(StreamIngestion):
    """Google Cloud Pub/Sub consumer implementation.

    This consumer handles message consumption from Google Cloud Pub/Sub
    subscriptions with proper error handling, acknowledgment, and retry logic.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize Pub/Sub consumer.

        Args:
            config: Configuration dictionary containing:
                - project_id: GCP project ID
                - subscription_name: Pub/Sub subscription name
                - max_messages: Maximum messages per pull (default: 100)
                - ack_deadline: Message acknowledgment deadline (default: 60)
                - flow_control: Flow control settings (optional)

        Raises:
            ImportError: If google-cloud-pubsub is not installed
        """
        if pubsub_v1 is None:
            raise ImportError(
                "google-cloud-pubsub is required for Pub/Sub consumer. "
                "Install with: pip install google-cloud-pubsub"
            )

        super().__init__(config)

        self.project_id = config["project_id"]
        self.subscription_name = config["subscription_name"]
        self.max_messages = config.get("max_messages", 100)
        self.ack_deadline = config.get("ack_deadline", 60)
        self.flow_control = config.get("flow_control", {})

        self.subscriber = None
        self.subscription_path = None
        self._ack_messages = []
        self._pull_timeout = config.get("pull_timeout", 10)
        self._executor = ThreadPoolExecutor(max_workers=4)

        self.logger = self.logger.bind(
            project_id=self.project_id, subscription=self.subscription_name
        )

    def connect(self) -> None:
        """Establish connection to Google Cloud Pub/Sub.

        Raises:
            ConnectionError: If connection fails
        """
        try:
            self.subscriber = pubsub_v1.SubscriberClient()
            self.subscription_path = self.subscriber.subscription_path(
                self.project_id, self.subscription_name
            )

            # Test connection by getting subscription info
            subscription_info = self.subscriber.get_subscription(
                request={"subscription": self.subscription_path}
            )

            self._connected = True
            self.logger.info(
                "Connected to Pub/Sub subscription",
                subscription_path=self.subscription_path,
                ack_deadline=subscription_info.ack_deadline_seconds,
            )

        except GoogleAPIError as e:
            self._connected = False
            error_msg = f"Failed to connect to Pub/Sub: {str(e)}"
            self.logger.error("Pub/Sub connection failed", error=str(e))
            raise ConnectionError(error_msg) from e

    def consume(self, batch_size: int = 100) -> Generator[StreamMessage, None, None]:
        """Consume messages from Pub/Sub subscription.

        Args:
            batch_size: Maximum number of messages to pull in one request

        Yields:
            StreamMessage: Standardized stream messages

        Raises:
            MessageProcessingError: If message processing fails
        """
        if not self._connected:
            raise MessageProcessingError("Not connected to Pub/Sub")

        # Use the smaller of batch_size and max_messages
        pull_size = min(batch_size, self.max_messages)

        try:
            # Configure flow control if specified
            flow_control_settings = None
            if self.flow_control:
                flow_control_settings = pubsub_v1.types.FlowControl(
                    max_messages=self.flow_control.get("max_messages", 1000),
                    max_bytes=self.flow_control.get(
                        "max_bytes", 100 * 1024 * 1024
                    ),  # 100MB
                )

            # Create pull request
            pull_request = pubsub_v1.PullRequest(
                subscription=self.subscription_path,
                max_messages=pull_size,
                allow_excess_messages=False,
            )

            # Pull messages with retry logic
            response = self.subscriber.pull(
                request=pull_request,
                retry=retry.Retry(deadline=self._pull_timeout),
                timeout=self._pull_timeout,
            )

            received_messages = response.received_messages
            self.logger.debug(
                "Pulled messages from Pub/Sub",
                count=len(received_messages),
                requested=pull_size,
            )

            for received_message in received_messages:
                try:
                    # Parse message data
                    message_data = self._parse_message_data(received_message.message)

                    # Create standardized message
                    stream_message = StreamMessage(
                        message_id=received_message.message.message_id,
                        data=message_data,
                        timestamp=datetime.fromtimestamp(
                            received_message.message.publish_time.timestamp()
                        ),
                        source="pubsub",
                        attributes=dict(received_message.message.attributes),
                        partition_key=received_message.message.attributes.get("key"),
                    )

                    # Store ack_id for acknowledgment
                    self._ack_messages.append(received_message.ack_id)

                    self._increment_message_count()
                    yield stream_message

                except Exception as e:
                    self._increment_error_count()
                    self.logger.error(
                        "Failed to process Pub/Sub message",
                        message_id=received_message.message.message_id,
                        error=str(e),
                    )
                    # Still add to ack list to prevent redelivery of bad messages
                    self._ack_messages.append(received_message.ack_id)

        except (GoogleAPIError, TimeoutError, DeadlineExceeded) as e:
            self._increment_error_count()
            error_msg = f"Failed to consume from Pub/Sub: {str(e)}"
            self.logger.error("Pub/Sub consumption failed", error=str(e))
            raise MessageProcessingError(error_msg) from e

    def acknowledge(self, message_ids: List[str]) -> None:
        """Acknowledge processed messages.

        Args:
            message_ids: List of message IDs to acknowledge (not used for Pub/Sub)

        Note:
            Pub/Sub uses ack_ids instead of message_ids for acknowledgment.
            This method acknowledges all messages in the current batch.
        """
        if not self._ack_messages:
            self.logger.debug("No messages to acknowledge")
            return

        try:
            # Acknowledge all messages in current batch
            self.subscriber.acknowledge(
                request={
                    "subscription": self.subscription_path,
                    "ack_ids": self._ack_messages,
                }
            )

            self.logger.info(
                "Acknowledged Pub/Sub messages", count=len(self._ack_messages)
            )

            # Clear acknowledged messages
            self._ack_messages = []

        except GoogleAPIError as e:
            self.logger.error(
                "Failed to acknowledge Pub/Sub messages",
                count=len(self._ack_messages),
                error=str(e),
            )
            # Don't clear ack_messages on failure to allow retry
            raise MessageProcessingError(
                f"Failed to acknowledge messages: {str(e)}"
            ) from e

    def close(self) -> None:
        """Close Pub/Sub connection and cleanup resources."""
        try:
            # Acknowledge any remaining messages
            if self._ack_messages:
                self.acknowledge([])

            # Close subscriber client
            if self.subscriber:
                self.subscriber.close()

            # Shutdown executor
            if self._executor:
                self._executor.shutdown(wait=True)

            self._connected = False
            self.logger.info("Closed Pub/Sub connection")

        except Exception as e:
            self.logger.error("Error closing Pub/Sub connection", error=str(e))

    def _parse_message_data(self, message) -> Dict[str, Any]:
        """Parse message data from Pub/Sub message.

        Args:
            message: Pub/Sub message object

        Returns:
            Parsed message data as dictionary

        Raises:
            MessageProcessingError: If parsing fails
        """
        try:
            # Try to decode as JSON first
            data_str = message.data.decode("utf-8")

            try:
                return json.loads(data_str)
            except json.JSONDecodeError:
                # If not JSON, return as string
                return {"raw_data": data_str}

        except UnicodeDecodeError:
            # If not UTF-8, return as base64
            import base64

            return {"raw_data_b64": base64.b64encode(message.data).decode("ascii")}

    def get_subscription_info(self) -> Dict[str, Any]:
        """Get information about the current subscription.

        Returns:
            Dictionary containing subscription information

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self.subscriber:
            raise ConnectionError("Not connected to Pub/Sub")

        try:
            subscription = self.subscriber.get_subscription(
                request={"subscription": self.subscription_path}
            )

            return {
                "name": subscription.name,
                "topic": subscription.topic,
                "ack_deadline_seconds": subscription.ack_deadline_seconds,
                "retain_acked_messages": subscription.retain_acked_messages,
                "message_retention_duration": subscription.message_retention_duration.total_seconds(),
                "push_config": bool(subscription.push_config.push_endpoint),
            }

        except GoogleAPIError as e:
            raise ConnectionError(f"Failed to get subscription info: {str(e)}") from e
