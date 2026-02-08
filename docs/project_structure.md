# Project Structure Overview

This document provides a comprehensive overview of the repository structure. The project follows a modular architecture separating source code (`src`), operational configurations (`ops`), utilities (`scripts`), and tests (`tests`).

## 📂 Root Directory

| Directory | Description |
|---|---|
| `.github/` | GitHub Actions workflows for CI/CD and Security pipelines. |
| `configs/` | Configuration files for models and pipeline parameters. |
| `data/` | Data directory for sample datasets and processed outputs. |
| `docs/` | Project documentation (architecture, guides, API reference). |
| `model_artifacts/` | Model metadata, feature definitions (`features.txt`), and versioning info. |
| `notebooks/` | Jupyter notebooks for data exploration and prototyping. |
| `ops/` | Infrastructure code, Docker configurations, and Kubernetes manifests. |
| `scripts/` | Utility scripts for setup, testing, and running demos. |
| `src/` | **Core application source code**. |
| `tests/` | Automated test suite (unit, integration, and performance). |

---

## 🌳 Detailed Structure

### 1. Source Code (`src/`)

The core application logic is located in `src/`.

```
src/
├── api/                # FastAPI application
│   ├── endpoints/      # API route definitions
│   └── schemas/        # Pydantic models for request/response validation
├── database/           # Database layer
│   └── models.py       # SQLModel/SQLAlchemy definitions
├── feature_engineering/# Data processing pipelines (Apache Beam)
├── feature_store/      # Feature retrieval logic (Redis/Postgres)
├── ingestion/          # Data consumers (Kafka, Kinesis, Pub/Sub)
├── models/             # ML Model logic
│   ├── training/       # Training scripts and classes
│   └── registry.py     # MLflow model registry interface
├── monitoring/         # Observability
│   └── prometheus.py   # Custom metric exporters
└── utils/              # Shared utilities (logging, config loading)
```

### 2. Operations & Infrastructure (`ops/`)

Deployment configurations and infrastructure-as-code.

```
ops/
├── docker/             # Dockerfiles for building services
│   ├── api/            # API Dockerfile
│   ├── mlflow/         # MLflow Server Dockerfile
│   └── beam/           # Beam Runner Dockerfile
├── envs/               # Environment configuration templates
│   └── .env.example    # Template for local environment variables
├── k8s/                # Kubernetes manifests (Kustomize)
│   ├── base/           # Base resources (Deployments, Services)
│   └── overlays/       # Environment specific patches
│       ├── staging/    # Staging configuration
│       └── production/ # Production configuration
├── local/              # Local development setup
│   ├── docker-compose.yml          # Base service definition
│   └── docker-compose.override.yml # Local development overrides (ports, volumes)
└── monitoring/         # Monitoring configuration
    ├── grafana/        # Dashboards and datasources
    └── prometheus/     # Prometheus access rules
```

### 3. CI/CD Workflows (`.github/workflows/`)

Automated pipelines driven by GitHub Actions.

```
.github/workflows/
├── ci.yml              # CI Pipeline: Linting, Unit/Integration/Performance Tests. Runs on PRs.
├── cd.yml              # CD Pipeline: Build Docker images, Deploy to K8s. Runs on push to main.
└── security.yml        # Security Pipeline: Bandit, Container Scans. Runs on schedule/PRs.
```

### 4. Tests (`tests/`)

Comprehensive test suite using `pytest`.

```
tests/
├── unit/               # Unit tests (isolated, mocked dependencies)
├── integration/        # Integration tests (requires DB/Redis containers)
├── performance/        # Latency and load tests for API
├── e2e/                # End-to-end user journey tests
└── fixtures/           # Shared test fixtures (conftest.py)
```

### 5. Utilities (`scripts/`)

Helper scripts for developers and CI.

```
scripts/
├── demo/               # End-to-end demo runners
├── setup/              # Setup scripts (Poetry, Pre-commit hooks)
└── test/               # Test runners (wrappers around pytest)
```

---

## Key Files

- **`pyproject.toml`**: Python project configuration, dependencies (Poetry), and tool settings (Black, Ruff, Pytest).
- **`README.md`**: Main entry point for the project.
- **`.gitignore`**: Specifies intentionally untracked files (e.g., `model_cache/`, `.venv`).
