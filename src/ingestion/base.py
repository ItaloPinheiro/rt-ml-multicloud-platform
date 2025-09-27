"""Base classes for multi-cloud stream ingestion.

This module provides abstract base classes and common data structures
for implementing streaming data ingestion from various sources like
GCP Pub/Sub, AWS Kinesis, and Apache Kafka.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional
import json
import structlog

logger = structlog.get_logger()


@dataclass
class StreamMessage:
    """Standardized stream message structure.

    This class provides a unified interface for messages from different
    streaming platforms, normalizing the data structure across sources.
    """
    message_id: str
    data: Dict[str, Any]
    timestamp: datetime
    source: str
    attributes: Dict[str, str] = field(default_factory=dict)
    partition_key: Optional[str] = None
    offset: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary format.

        Returns:
            Dictionary representation of the message
        """
        return {
            "message_id": self.message_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "attributes": self.attributes,
            "partition_key": self.partition_key,
            "offset": self.offset
        }

    def to_json(self) -> str:
        """Convert message to JSON string.

        Returns:
            JSON string representation of the message
        """
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreamMessage":
        """Create StreamMessage from dictionary.

        Args:
            data: Dictionary containing message data

        Returns:
            StreamMessage instance
        """
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        elif timestamp is None:
            timestamp = datetime.utcnow()

        return cls(
            message_id=data["message_id"],
            data=data["data"],
            timestamp=timestamp,
            source=data["source"],
            attributes=data.get("attributes", {}),
            partition_key=data.get("partition_key"),
            offset=data.get("offset")
        )


class StreamIngestionError(Exception):
    """Base exception for stream ingestion errors."""
    pass


class ConnectionError(StreamIngestionError):
    """Raised when connection to stream source fails."""
    pass


class MessageProcessingError(StreamIngestionError):
    """Raised when message processing fails."""
    pass


class StreamIngestion(ABC):
    """Abstract base class for stream ingestion implementations.

    This class defines the interface that all stream ingestion
    implementations must follow, ensuring consistency across
    different streaming platforms.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize stream ingestion.

        Args:
            config: Configuration dictionary specific to the stream source
        """
        self.config = config
        self.logger = logger.bind(
            source=self.__class__.__name__,
            config_keys=list(config.keys())
        )
        self._connected = False
        self._message_count = 0
        self._error_count = 0

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the stream source.

        Raises:
            ConnectionError: If connection fails
        """
        pass

    @abstractmethod
    def consume(self, batch_size: int = 100) -> Generator[StreamMessage, None, None]:
        """Consume messages from the stream.

        Args:
            batch_size: Maximum number of messages to retrieve in one batch

        Yields:
            StreamMessage: Individual stream messages

        Raises:
            MessageProcessingError: If message processing fails
        """
        pass

    @abstractmethod
    def acknowledge(self, message_ids: List[str]) -> None:
        """Acknowledge successful processing of messages.

        Args:
            message_ids: List of message IDs to acknowledge
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connection to the stream source."""
        pass

    def is_connected(self) -> bool:
        """Check if connection is established.

        Returns:
            True if connected, False otherwise
        """
        return self._connected

    def get_stats(self) -> Dict[str, Any]:
        """Get ingestion statistics.

        Returns:
            Dictionary containing ingestion statistics
        """
        return {
            "message_count": self._message_count,
            "error_count": self._error_count,
            "connected": self._connected,
            "source": self.__class__.__name__
        }

    def _increment_message_count(self) -> None:
        """Increment processed message counter."""
        self._message_count += 1

    def _increment_error_count(self) -> None:
        """Increment error counter."""
        self._error_count += 1

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class BatchProcessor:
    """Utility class for processing messages in batches.

    This class provides helper methods for efficient batch processing
    of stream messages, including error handling and retry logic.
    """

    def __init__(self, batch_size: int = 100, max_retries: int = 3):
        """Initialize batch processor.

        Args:
            batch_size: Size of message batches to process
            max_retries: Maximum number of retry attempts for failed messages
        """
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.logger = logger.bind(component="BatchProcessor")

    def process_batch(
        self,
        messages: List[StreamMessage],
        processor_func: callable
    ) -> Dict[str, List[StreamMessage]]:
        """Process a batch of messages.

        Args:
            messages: List of messages to process
            processor_func: Function to apply to each message

        Returns:
            Dictionary with 'success' and 'failed' message lists
        """
        successful = []
        failed = []

        for message in messages:
            try:
                processed_message = processor_func(message)
                successful.append(processed_message)
            except Exception as e:
                self.logger.error(
                    "Message processing failed",
                    message_id=message.message_id,
                    error=str(e)
                )
                failed.append(message)

        self.logger.info(
            "Batch processing completed",
            total=len(messages),
            successful=len(successful),
            failed=len(failed)
        )

        return {
            "success": successful,
            "failed": failed
        }