
import pytest
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure retry logic for resilience
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount('http://', HTTPAdapter(max_retries=retries))

BASE_URL = "http://localhost:8000"

@pytest.mark.performance
def test_health_endpoint_latency():
    """
    Performance test: Health check should respond within 200ms
    """
    total_time = 0
    iterations = 10
    
    # Warmup
    try:
        session.get(f"{BASE_URL}/health", timeout=5)
    except requests.exceptions.ConnectionError:
        pytest.fail(f"Could not connect to {BASE_URL}. Is the API running?")

    # Measure
    for _ in range(iterations):
        start_time = time.time()
        response = session.get(f"{BASE_URL}/health", timeout=2)
        end_time = time.time()
        
        assert response.status_code == 200
        total_time += (end_time - start_time)
    
    avg_latency = total_time / iterations
    print(f"\nAverage Latency: {avg_latency:.4f}s")
    
    # Assert average latency is under 200ms
    assert avg_latency < 0.200, f"Average latency {avg_latency:.4f}s exceeded 200ms threshold"

@pytest.mark.performance
def test_predict_endpoint_latency():
    """
    Performance test: Prediction endpoint should respond within 500ms
    """
    # Sample payload for fraud detection model
    payload = {
        "is_fraud": 0,
        "TransactionAmt": 100.0,
        "ProductCD": "W",
        "card1": 10000,
        "card2": 111,
        "card3": 150,
        "card4": "visa",
        "card5": 226,
        "card6": "debit",
        "addr1": 315,
        "addr2": 87,
        "dist1": 100,
        "P_emaildomain": "gmail.com",
        "R_emaildomain": "gmail.com"
        # Add minimal required fields to pass validation
    }
    
    # Try prediction if model is loaded (might not be in fresh env)
    # Just checking API response time here
    try:
        start_time = time.time()
        # Using a dummy payload that might fail validation but hits the API layer
        response = session.post(f"{BASE_URL}/predict/fraud_detector", json=payload, timeout=2)
        end_time = time.time()
        
        # We accept 200 or 4xx (validation error) - just measuring latency
        # 5xx would be a failure
        assert response.status_code < 500
        
        latency = end_time - start_time
        assert latency < 0.500, f"Prediction latency {latency:.4f}s exceeded 500ms threshold"
        
    except requests.exceptions.ConnectionError:
        pytest.skip("API not reachable")
