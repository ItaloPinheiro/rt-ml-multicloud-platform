# API Reference

The Model Serving API is built with FastAPI. It provides endpoints for prediction, health checks, and metrics.

**Base URL**: `http://localhost:8000`

## Interactive Documentation

*   **Swagger UI**: [/docs](http://localhost:8000/docs)
*   **ReDoc**: [/redoc](http://localhost:8000/redoc)

## Endpoints

### Prediction

#### `POST /predict`

Make a single prediction.

**Request Body:**

```json
{
  "model_name": "fraud_detector",
  "version": "latest",
  "features": {
    "amount": 250.00,
    "merchant_category": "electronics",
    "hour_of_day": 14
  },
  "return_probabilities": true
}
```

**Response:**

```json
{
  "prediction": 1,
  "probabilities": [0.1, 0.9],
  "model_name": "fraud_detector",
  "model_version": "2",
  "latency_ms": 15.2
}
```

#### `POST /predict/batch`

Make predictions for multiple instances. Optimized for high throughput.

**Request Body:**

```json
{
  "model_name": "fraud_detector",
  "instances": [
    {"amount": 100.0},
    {"amount": 500.0}
  ]
}
```

### Management

#### `GET /health`

Check API and dependency health.

**Response:**

```json
{
  "status": "healthy",
  "checks": {
    "api": "healthy",
    "redis": "healthy",
    "mlflow": "healthy"
  }
}
```

#### `GET /metrics`

Prometheus metrics endpoint.

### Models

#### `GET /models`

List currently loaded models and their versions.

#### `POST /models/reload`

Force reload of specific models.
