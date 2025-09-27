"""Integration tests for the FastAPI application."""

import pytest
import asyncio
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock

from src.api.main import app
from src.api.schemas import PredictionRequest, BatchPredictionRequest


class TestAPIIntegration:
    """Test API integration scenarios."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_model_manager(self):
        """Mock model manager for testing."""
        mock_manager = Mock()

        # Mock successful prediction
        mock_manager.predict = AsyncMock(return_value={
            "prediction": 0,
            "probabilities": [0.8, 0.2],
            "model_name": "fraud_detector",
            "model_version": "1.0",
            "timestamp": datetime.utcnow(),
            "latency_ms": 25.5,
            "features_used": {"amount": 250.0, "merchant_category": "electronics"}
        })

        # Mock batch prediction
        mock_manager.batch_predict = AsyncMock(return_value={
            "predictions": [0, 1],
            "probabilities": [[0.8, 0.2], [0.3, 0.7]],
            "model_name": "fraud_detector",
            "model_version": "1.0",
            "timestamp": datetime.utcnow(),
            "batch_size": 2,
            "total_latency_ms": 45.0,
            "avg_latency_ms": 22.5
        })

        # Mock model info
        mock_manager.get_model_info = AsyncMock(return_value={
            "name": "fraud_detector",
            "versions": ["1.0", "1.1"],
            "current_stage": "Production",
            "description": "Fraud detection model",
            "metrics": {"accuracy": 0.95, "precision": 0.92}
        })

        return mock_manager

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "timestamp" in data
        assert "version" in data
        assert "checks" in data

    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert "version" in data

    @patch("src.api.main.model_manager")
    def test_single_prediction(self, mock_model_manager, client, sample_prediction_request):
        """Test single prediction endpoint."""
        mock_model_manager.predict = AsyncMock(return_value={
            "prediction": 0,
            "probabilities": [0.8, 0.2],
            "model_name": "fraud_detector",
            "model_version": "1.0",
            "timestamp": datetime.utcnow(),
            "latency_ms": 25.5
        })

        response = client.post("/predict", json=sample_prediction_request)
        assert response.status_code == 200

        data = response.json()
        assert "prediction" in data
        assert "probabilities" in data
        assert "model_name" in data
        assert "model_version" in data
        assert "timestamp" in data
        assert "latency_ms" in data

        # Verify model manager was called
        mock_model_manager.predict.assert_called_once()

    @patch("src.api.main.model_manager")
    def test_batch_prediction(self, mock_model_manager, client, sample_batch_prediction_request):
        """Test batch prediction endpoint."""
        mock_model_manager.batch_predict = AsyncMock(return_value={
            "predictions": [0, 1],
            "probabilities": [[0.8, 0.2], [0.3, 0.7]],
            "model_name": "fraud_detector",
            "model_version": "1.0",
            "timestamp": datetime.utcnow(),
            "batch_size": 2,
            "total_latency_ms": 45.0,
            "avg_latency_ms": 22.5
        })

        response = client.post("/predict/batch", json=sample_batch_prediction_request)
        assert response.status_code == 200

        data = response.json()
        assert "predictions" in data
        assert "probabilities" in data
        assert "batch_size" in data
        assert "total_latency_ms" in data
        assert "avg_latency_ms" in data

        # Verify model manager was called
        mock_model_manager.batch_predict.assert_called_once()

    def test_prediction_validation_error(self, client):
        """Test prediction endpoint with validation errors."""
        # Missing required fields
        invalid_request = {
            "model_name": "fraud_detector"
            # Missing features
        }

        response = client.post("/predict", json=invalid_request)
        assert response.status_code == 422

        data = response.json()
        assert "detail" in data

    def test_batch_prediction_validation_error(self, client):
        """Test batch prediction with validation errors."""
        # Empty instances
        invalid_request = {
            "instances": [],
            "model_name": "fraud_detector"
        }

        response = client.post("/predict/batch", json=invalid_request)
        assert response.status_code == 422

    def test_batch_prediction_size_limit(self, client):
        """Test batch prediction size limit."""
        # Too many instances
        large_request = {
            "instances": [{"feature": i} for i in range(1001)],  # Over limit
            "model_name": "fraud_detector"
        }

        response = client.post("/predict/batch", json=large_request)
        assert response.status_code == 422

    @patch("src.api.main.model_manager")
    def test_model_info_endpoint(self, mock_model_manager, client):
        """Test model info endpoint."""
        mock_model_manager.get_model_info = AsyncMock(return_value={
            "name": "fraud_detector",
            "versions": ["1.0", "1.1"],
            "current_stage": "Production",
            "description": "Fraud detection model"
        })

        response = client.get("/models/fraud_detector")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "fraud_detector"
        assert "versions" in data
        assert "current_stage" in data

    @patch("src.api.main.model_manager")
    def test_model_not_found(self, mock_model_manager, client):
        """Test model info for non-existent model."""
        mock_model_manager.get_model_info = AsyncMock(side_effect=ValueError("Model not found"))

        response = client.get("/models/nonexistent_model")
        assert response.status_code == 404

    @patch("src.api.main.model_manager")
    def test_prediction_model_error(self, mock_model_manager, client, sample_prediction_request):
        """Test prediction with model error."""
        mock_model_manager.predict = AsyncMock(side_effect=RuntimeError("Model inference failed"))

        response = client.post("/predict", json=sample_prediction_request)
        assert response.status_code == 500

        data = response.json()
        assert "error" in data
        assert "Model inference failed" in data["message"]

    def test_metrics_endpoint(self, client):
        """Test metrics endpoint."""
        response = client.get("/metrics")

        # Should return either Prometheus format or JSON
        assert response.status_code == 200

    def test_api_versioning(self, client):
        """Test API version in responses."""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert "version" in data
        assert isinstance(data["version"], str)

    def test_cors_headers(self, client):
        """Test CORS headers are present."""
        response = client.options("/predict")
        assert response.status_code == 200

        # Check for CORS headers
        assert "access-control-allow-origin" in response.headers
        assert "access-control-allow-methods" in response.headers

    @patch("src.api.main.model_manager")
    def test_request_timeout(self, mock_model_manager, client, sample_prediction_request):
        """Test request timeout handling."""
        # Mock a slow prediction
        async def slow_predict(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than typical timeout
            return {"prediction": 0}

        mock_model_manager.predict = slow_predict

        response = client.post("/predict", json=sample_prediction_request, timeout=1)
        # This should timeout on the client side
        # The actual behavior depends on the test client implementation

    def test_large_payload_handling(self, client):
        """Test handling of large payloads."""
        # Create a large feature dictionary
        large_features = {f"feature_{i}": i for i in range(1000)}

        large_request = {
            "features": large_features,
            "model_name": "fraud_detector"
        }

        response = client.post("/predict", json=large_request)
        # Should handle large payloads gracefully
        assert response.status_code in [200, 413, 422]  # Success, too large, or validation error

    def test_content_type_validation(self, client):
        """Test content type validation."""
        # Send non-JSON data
        response = client.post(
            "/predict",
            data="not json",
            headers={"content-type": "text/plain"}
        )
        assert response.status_code == 422

    def test_method_not_allowed(self, client):
        """Test method not allowed responses."""
        # GET on prediction endpoint
        response = client.get("/predict")
        assert response.status_code == 405

        # PUT on health endpoint
        response = client.put("/health")
        assert response.status_code == 405


class TestAPIMiddleware:
    """Test API middleware functionality."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_request_logging_middleware(self, client):
        """Test request logging middleware."""
        response = client.get("/health")
        assert response.status_code == 200

        # Check for request ID header
        assert "x-request-id" in response.headers

    def test_timing_middleware(self, client):
        """Test request timing middleware."""
        response = client.get("/health")
        assert response.status_code == 200

        # Check for timing header
        assert "x-process-time" in response.headers
        timing = float(response.headers["x-process-time"])
        assert timing >= 0

    def test_error_handling_middleware(self, client):
        """Test error handling middleware."""
        # This would require an endpoint that raises an exception
        # For now, test that invalid endpoints return proper error format
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data


class TestAPIPerformance:
    """Test API performance characteristics."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @patch("src.api.main.model_manager")
    def test_concurrent_requests(self, mock_model_manager, client, sample_prediction_request):
        """Test handling of concurrent requests."""
        mock_model_manager.predict = AsyncMock(return_value={
            "prediction": 0,
            "probabilities": [0.8, 0.2],
            "model_name": "fraud_detector",
            "model_version": "1.0",
            "timestamp": datetime.utcnow(),
            "latency_ms": 25.5
        })

        # Send multiple concurrent requests
        import concurrent.futures
        import threading

        def make_request():
            return client.post("/predict", json=sample_prediction_request)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            responses = [future.result() for future in futures]

        # All requests should succeed
        for response in responses:
            assert response.status_code == 200

    def test_memory_usage_stability(self, client, sample_prediction_request):
        """Test that memory usage remains stable under load."""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Make many requests
        for _ in range(100):
            response = client.get("/health")
            assert response.status_code == 200

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        # Memory increase should be reasonable (less than 50MB)
        assert memory_increase < 50 * 1024 * 1024