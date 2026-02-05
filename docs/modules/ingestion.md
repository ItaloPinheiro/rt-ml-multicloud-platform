# Ingestion Module

The ingestion module (`src/ingestion`) handles the consumption of data from various streaming sources.

## Overview

The module uses a strategy pattern to support multiple cloud providers. All consumers inherit from the abstract base class `StreamIngestion`.

## Supported Sources

### Kafka / Redpanda
*   **Class**: `KafkaIngestion`
*   **Library**: `confluent-kafka`
*   **Config**: `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_SECURITY_PROTOCOL`

### AWS Kinesis
*   **Class**: `KinesisIngestion`
*   **Library**: `boto3`
*   **Config**: `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

### GCP Pub/Sub
*   **Class**: `PubSubIngestion`
*   **Library**: `google-cloud-pubsub`
*   **Config**: `GCP_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS`

## Usage

```python
from src.ingestion.kafka import KafkaIngestion
from src.utils.config import get_config

config = get_config()
ingestion = KafkaIngestion(config.kafka)

with ingestion:
    for message in ingestion.consume():
        print(f"Received: {message.data}")
        ingestion.acknowledge([message.message_id])
```

## Data Model

All messages are normalized to `StreamMessage`:

```python
@dataclass
class StreamMessage:
    message_id: str
    data: Dict[str, Any]
    timestamp: datetime
    source: str
    attributes: Dict[str, str]
```
