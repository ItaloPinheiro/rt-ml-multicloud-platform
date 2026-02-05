# Real-Time ML Pipeline Platform

Production-ready machine learning platform for real-time streaming data processing, model management, and high-performance API serving.

## Documentation

Full documentation is available in the [docs/](docs/README.md) directory.

*   **[Setup Guide](docs/guides/setup.md)**: Get started with installation and local setup.
*   **[Architecture](docs/architecture/overview.md)**: Understand the system design and components.
*   **[API Reference](docs/api/reference.md)**: Detailed API documentation.
*   **[Running the Demo](docs/guides/demo.md)**: Step-by-step guide to run the end-to-end demo.

## Features

*   **Multi-cloud streaming**: Kafka, AWS Kinesis, and GCP Pub/Sub consumers.
*   **Feature Store**: Low-latency Redis cache with PostgreSQL persistence.
*   **Model Serving**: High-performance FastAPI server with async support.
*   **MLflow Integration**: Automated model versioning and registry.
*   **Observability**: Built-in Prometheus metrics and Grafana dashboards.

## Quick Start

```bash
# Clone repository
git clone <repository-url>
cd rt-ml-multicloud-platform

# Setup environment
cp .env.example .env

# Start services
docker-compose -f ops/local/docker-compose.yml -f ops/local/docker-compose.override.yml up -d

# Run demo
./scripts/demo/demo.sh
```

## License

MIT License - see [LICENSE](LICENSE) file for details.