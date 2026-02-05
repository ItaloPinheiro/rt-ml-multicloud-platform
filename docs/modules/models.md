# Models Module

The models module (`src/models`) contains the logic for training, evaluating, and managing machine learning models.

## Training Pipeline

The training pipeline is designed to be modular and reproducible.

1.  **Data Loading**: Fetches historical data from the Feature Store (Offline Store).
2.  **Preprocessing**: Applies the same transformations used in serving.
3.  **Training**: Trains the model (e.g., Scikit-Learn, XGBoost).
4.  **Evaluation**: Calculates metrics (Accuracy, F1, ROC-AUC).
5.  **Registration**: Logs the model and metrics to MLflow.

## MLflow Integration

We use MLflow for:
*   **Experiment Tracking**: Logging parameters, metrics, and artifacts.
*   **Model Registry**: Versioning models and managing lifecycle stages (Staging, Production).

## Adding a New Model

To add a new model type:

1.  Create a new trainer class inheriting from `BaseTrainer`.
2.  Implement `train()` and `evaluate()` methods.
3.  Use the `MLflowLogger` to track progress.

## usage

```python
from src.models.training.trainer import FraudDetectionTrainer

trainer = FraudDetectionTrainer()
model, metrics = trainer.train(data_path="data/raw/fraud.csv")

print(f"Training complete. Metrics: {metrics}")
```
