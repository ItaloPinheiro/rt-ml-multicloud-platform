#!/bin/bash

# Train model using the beam-runner container
# This is the proper way to run training in a containerized environment

echo "Starting model training in Docker container..."

# First, ensure required services are running
echo "Starting required services (MLflow, MinIO, PostgreSQL)..."
docker-compose up -d mlflow-server mlflow-minio mlflow-db

# Wait for services to be ready
echo "Waiting for services to be ready..."
sleep 10

# Start beam-runner with the beam profile
echo "Starting beam-runner container..."
docker-compose --profile beam up -d beam-runner

# Wait for beam-runner to be ready
echo "Waiting for beam-runner to be ready..."
sleep 5

# Run the training script inside the beam-runner container
echo "Running training script..."
docker-compose exec -T beam-runner python -m src.models.training.train \
    --data-path /app/sample_data/demo/datasets/fraud_detection.csv \
    --mlflow-uri http://mlflow-server:5000 \
    --experiment fraud_detection \
    --model-name fraud_detector

echo "Training complete!"