# Setup and Installation

This guide covers the steps to set up the Real-Time ML Multicloud Platform for local development.

## Prerequisites

Ensure you have the following installed:

*   **Docker & Docker Compose**: For running services.
*   **Python 3.11+**: For local development.
*   **Poetry**: For dependency management.
*   **Git**: For version control.
*   **Hardware**: Minimum 8GB RAM recommended.

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd rt-ml-multicloud-platform
```

### 2. Install Python Dependencies

We use [Poetry](https://python-poetry.org/) for dependency management.

```bash
# Install Poetry if you haven't already
pip install poetry

# Install project dependencies
poetry install

# Activate the virtual environment
poetry shell
```

### 3. Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Review the `.env` file and adjust settings if necessary. For local development, the defaults usually work fine.

## Starting Services

The platform uses Docker Compose to run infrastructure services (Redis, PostgreSQL, MLflow, MinIO, etc.).

```bash
# Start all services in detached mode
docker-compose up -d
```

Wait for about 30-60 seconds for all services to initialize.

## Verification

Check if the services are running correctly:

```bash
# Check API health
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy", ...}
```

You can also access the following interfaces:

*   **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
*   **MLflow UI**: [http://localhost:5000](http://localhost:5000)
*   **Grafana**: [http://localhost:3001](http://localhost:3001) (Default credentials: `admin` / `admin123`)
*   **Prometheus**: [http://localhost:9090](http://localhost:9090)
*   **MinIO Console**: [http://localhost:9001](http://localhost:9001) (Default credentials: `minioadmin` / `minioadmin123`)

## Troubleshooting

### Services fail to start

Check the logs for specific services:

```bash
docker-compose logs -f model-api
docker-compose logs -f mlflow-server
```

### Port conflicts

Ensure ports 8000, 5000, 6379, 5432, 9090, 3000 are free. You can change ports in `docker-compose.yml` and `.env` if needed.
