# Data Flow

This document describes how data moves through the system, from ingestion to prediction.

## 1. Ingestion Flow

Raw events are ingested from external sources.

```mermaid
sequenceDiagram
    participant Source as Kafka/Kinesis/PubSub
    participant Ingestion as StreamIngestion
    participant Beam as Beam Pipeline
    participant FS as Feature Store

    Source->>Ingestion: Raw Event
    Ingestion->>Ingestion: Normalize to StreamMessage
    Ingestion->>Beam: Process Message
    Beam->>Beam: Apply Transformations
    Beam->>FS: Write Features (Redis + DB)
```

## 2. Prediction Flow

The API handles prediction requests by fetching features and querying the model.

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant FS as Feature Store (Redis)
    participant Model as Loaded Model

    Client->>API: POST /predict (Entity ID)
    API->>FS: Get Features (Entity ID)
    
    alt Cache Hit
        FS-->>API: Return Cached Features
    else Cache Miss
        FS->>DB: Fetch from DB
        DB-->>FS: Return Features
        FS-->>API: Return Features
    end

    API->>Model: Predict(Features)
    Model-->>API: Prediction Result
    API-->>Client: JSON Response
```

## 3. Model Update Flow

The system automatically updates models when new versions are available in MLflow.

```mermaid
sequenceDiagram
    participant MLflow
    participant Updater as ModelUpdateManager
    participant Manager as ModelManager
    participant Cache as Model Cache

    loop Every 60s
        Updater->>MLflow: Check for new versions
        
        alt New Version Found
            MLflow-->>Updater: Version Info
            Updater->>Manager: Load Model
            Manager->>MLflow: Download Artifacts
            Manager->>Cache: Update Cache
            Updater->>Log: Log Update Success
        end
    end
```
