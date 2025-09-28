#!/bin/sh
# MinIO entrypoint script that creates bucket on startup

# Start MinIO server in background
minio server /data --console-address ":9001" &
MINIO_PID=$!

# Wait for MinIO to be ready
echo "Waiting for MinIO to start..."
until curl -f http://localhost:9000/minio/health/live > /dev/null 2>&1; do
    sleep 1
done
echo "MinIO is ready"

# Configure mc and create bucket
mc alias set local http://localhost:9000 minioadmin minioadmin123
mc mb -p local/mlflow 2>/dev/null || echo "Bucket already exists"
mc anonymous set download local/mlflow 2>/dev/null || echo "Anonymous access already configured"
echo "MinIO bucket setup complete"

# Keep MinIO running in foreground
wait $MINIO_PID