"""Simple prediction endpoint that loads model from file."""
import pickle
import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any
import os

router = APIRouter()

# Global model and scaler
MODEL = None
SCALER = None

def load_model():
    """Load model and scaler from files."""
    global MODEL, SCALER

    model_path = "/app/fraud_detector.pkl"
    scaler_path = "/app/scaler.pkl"

    # Try local paths if container paths don't exist
    if not os.path.exists(model_path):
        model_path = "models/fraud_detector.pkl"
    if not os.path.exists(scaler_path):
        scaler_path = "models/scaler.pkl"

    try:
        with open(model_path, 'rb') as f:
            MODEL = pickle.load(f)
        with open(scaler_path, 'rb') as f:
            SCALER = pickle.load(f)
        return True
    except Exception as e:
        print(f"Failed to load model: {e}")
        return False

class SimplePredictionRequest(BaseModel):
    features: Dict[str, Any]

class SimplePredictionResponse(BaseModel):
    prediction: int
    probability: float
    status: str

@router.post("/simple_predict", response_model=SimplePredictionResponse)
async def simple_predict(request: SimplePredictionRequest):
    """Simple prediction endpoint."""

    # Load model if not loaded
    if MODEL is None or SCALER is None:
        if not load_model():
            return SimplePredictionResponse(
                prediction=0,
                probability=0.0,
                status="error: model not loaded"
            )

    try:
        # Expected feature order (from training)
        feature_order = [
            'hour_of_day', 'day_of_week', 'is_weekend',
            'transaction_count_24h', 'avg_amount_30d', 'risk_score',
            'amount', 'merchant_category_encoded', 'payment_method_encoded'
        ]

        # Extract features in correct order
        feature_values = []
        for feature in feature_order:
            if feature in request.features:
                feature_values.append(request.features[feature])
            else:
                # Use defaults for missing features
                if feature == 'is_weekend':
                    feature_values.append(0)  # False as 0
                elif feature.endswith('_encoded'):
                    feature_values.append(0)  # Default encoding
                else:
                    feature_values.append(0.0)  # Default numeric

        # Convert to numpy array and reshape
        X = np.array([feature_values])

        # Scale features
        X_scaled = SCALER.transform(X)

        # Make prediction
        prediction = MODEL.predict(X_scaled)[0]
        probability = MODEL.predict_proba(X_scaled)[0].max()

        return SimplePredictionResponse(
            prediction=int(prediction),
            probability=float(probability),
            status="success"
        )
    except Exception as e:
        return SimplePredictionResponse(
            prediction=0,
            probability=0.0,
            status=f"error: {str(e)}"
        )