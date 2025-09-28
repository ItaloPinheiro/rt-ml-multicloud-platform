# Model Management Strategy

## Overview
The platform implements automatic model loading and updates from MLflow with in-memory caching and zero-downtime deployments.

## Model Loading Flow

```
1. API Startup → Load latest "Production" model from MLflow
2. Cache model in memory (FastModelLoader)
3. Background task checks for updates every 60s
4. Hot-swap models without service interruption
```

## Components

### FastModelLoader (`src/api/fast_model_loader.py`)
- **In-memory cache**: Stores up to 5 models
- **LRU eviction**: Removes least recently used models
- **Thread-safe**: Concurrent access support
- **Lazy loading**: Models loaded on first request

### ModelUpdater (`src/api/model_updater.py`)
- **Auto-refresh**: Checks MLflow every 60 seconds
- **Version tracking**: Detects new model versions
- **Background updates**: Non-blocking model updates
- **Graceful transitions**: Old model serves until new one ready

## Configuration

```python
# Environment variables
MODEL_CACHE_SIZE=5          # Max models in memory
MODEL_UPDATE_INTERVAL=60    # Update check interval (seconds)
MLFLOW_TRACKING_URI=http://mlflow-server:5000

# Model stages (MLflow)
- "None"        # Development models
- "Staging"     # Testing models
- "Production"  # Active models (auto-loaded)
- "Archived"    # Retired models
```

## Automatic Update Process

### 1. Training & Registration
```bash
# Train new model
python scripts/model_scripts/train_model.py

# Model automatically registered in MLflow
# Transitions to "Production" stage when ready
```

### 2. Detection & Loading
```python
# Background task (runs every 60s)
async def check_for_updates():
    latest = mlflow.get_latest_model("Production")
    if latest.version != current.version:
        await load_new_model(latest)
        swap_models()  # Atomic operation
```

### 3. Zero-Downtime Swap
```python
# Atomic model replacement
old_model = current_model
current_model = new_model  # Instant swap
await cleanup_old_model(old_model)  # Async cleanup
```

## Manual Controls

### Force Model Reload
```bash
# Trigger immediate update check
curl -X POST http://localhost:8000/models/reload

# Response
{"status": "reloaded", "model_version": "2"}
```

### Check Current Model
```bash
curl http://localhost:8000/models/current

# Response
{
  "name": "fraud_detection_model",
  "version": "2",
  "stage": "Production",
  "loaded_at": "2024-01-20T10:30:00Z"
}
```

## Model Lifecycle

```
Training → Registration → Staging → Production → Serving
   ↓           ↓            ↓          ↓           ↓
Beam/Local  MLflow     Validation  Auto-load   API Cache
```

## Performance Metrics

- **Load time**: < 5 seconds for typical models
- **Update latency**: < 100ms for model swap
- **Memory usage**: ~200MB per cached model
- **Cache hit rate**: > 95% in production

## Monitoring

### Key Metrics
```bash
# Model version in use
curl http://localhost:8000/metrics | grep model_version

# Cache performance
curl http://localhost:8000/metrics | grep cache_hits

# Update failures
curl http://localhost:8000/metrics | grep model_update_errors
```

### Logs
```bash
# Watch model updates
docker-compose logs -f model-api | grep "Model"

# Sample output
[INFO] Loading model version 2 from MLflow
[INFO] Model loaded successfully in 2.3s
[INFO] Swapped to model version 2
[INFO] Cleaned up model version 1
```

## Failure Handling

### Fallback Strategy
1. New model fails to load → Keep current model
2. MLflow unavailable → Use cached model
3. No cached model → Return 503 Service Unavailable

### Recovery
```python
# Automatic retry with exponential backoff
retry_intervals = [5, 10, 30, 60]  # seconds

# Health check endpoint
GET /health → {"model_loaded": true/false}
```

## Best Practices

1. **Stage Transitions**: Always test in "Staging" before "Production"
2. **Version Tags**: Tag models with training metadata
3. **Rollback Plan**: Keep previous version in "Archived"
4. **Monitor Metrics**: Track prediction latency after updates
5. **Gradual Rollout**: Use multiple API instances for canary deployments

## Quick Commands

```bash
# Train and deploy new model
./scripts/model_scripts/train_model.py
# Model auto-transitions to Production when metrics pass threshold

# Monitor deployment
watch 'curl -s localhost:8000/models/current | jq .'

# Rollback if needed (in MLflow UI)
# 1. Set current Production model to Archived
# 2. Set previous model to Production
# 3. API auto-loads previous version within 60s
```

## Architecture Benefits

- **No downtime**: Models swap atomically
- **Fast rollback**: Previous versions cached
- **Memory efficient**: LRU cache management
- **Fault tolerant**: Fallback to cached models
- **Observable**: Metrics and logging throughout