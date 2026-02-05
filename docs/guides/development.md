# Development Guide

This guide describes the development workflow, code standards, and testing procedures.

## Project Structure

```
src/
├── api/                # FastAPI application
├── feature_store/      # Feature Store logic
├── ingestion/          # Data ingestion consumers
├── feature_engineering/# Beam pipelines
├── models/             # Model training code
├── monitoring/         # Metrics and observability
├── database/           # Database models
└── utils/              # Shared utilities
tests/                  # Test suite
```

## Code Style

We use `black` for formatting, `ruff` for linting, and `mypy` for type checking.

```bash
# Format code
poetry run black src/ tests/

# Lint code
poetry run ruff check src/ tests/

# Type check
poetry run mypy src/
```

## Testing

We use `pytest` for testing.

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=src --cov-report=html
```

### Writing Tests

*   **Unit Tests**: Place in `tests/unit/`. Mock external dependencies (Redis, DB, MLflow).
*   **Integration Tests**: Place in `tests/integration/`. These may require running Docker services.

## Adding a New Feature

1.  **Create a Branch**: `git checkout -b feat/your-feature-name`
2.  **Implement Changes**: Write code and tests.
3.  **Verify**: Run formatters, linters, and tests.
4.  **Submit PR**: Push to GitHub and create a Pull Request.

## Adding a New Model

1.  Define training logic in `src/models/training/`.
2.  Update `src/models/training/trainer.py` if needed.
3.  Train the model and register it to MLflow.
4.  The API will automatically pick up the new model version if it's tagged as "Production" or if it's the latest version (depending on configuration).

## Database Migrations

We use `alembic` (if configured) or direct SQLAlchemy models. Ensure `src/database/models.py` is updated when changing schemas.
