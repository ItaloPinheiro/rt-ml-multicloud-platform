# Configuration Strategy

This document explains the improved configuration strategy for the RT ML platform.

## Configuration Loading Order

The system uses a hierarchical configuration loading approach:

```
1. Default values (in code)
2. Base component configs (configs/api/base.yaml, configs/beam/base.yaml, etc.)
3. Environment-specific configs (configs/development.yaml, configs/staging.yaml, configs/production.yaml)
4. Environment variables (highest priority)
```

## File Structure

```
configs/
├── development.yaml          # Main dev environment config
├── staging.yaml             # Main staging environment config
├── production.yaml          # Main production environment config
├── api/
│   ├── base.yaml           # Base API configuration (environment-agnostic)
│   ├── middleware.yaml     # Middleware-specific settings
│   └── serving.yaml        # Model serving settings
├── beam/
│   ├── base.yaml           # Base Beam configuration
│   ├── pipelines.yaml      # Pipeline definitions
│   └── transforms.yaml     # Transform configurations
├── mlflow/
│   ├── base.yaml           # Base MLflow configuration
│   ├── tracking.yaml       # Tracking server settings
│   └── deployment.yaml     # Model deployment settings
└── monitoring/
    ├── base.yaml           # Base monitoring configuration
    ├── metrics.yaml        # Metrics definitions
    └── alerts.yaml         # Alert rules and notifications
```

## Configuration Loading Logic

### 1. Component Configuration Loading

Each component loads its configuration by:
1. Loading `configs/{component}/base.yaml` (base settings)
2. Loading `configs/{component}/*.yaml` (specific configurations)
3. Merging with main environment config `configs/{environment}.yaml`
4. Applying environment variable overrides

### 2. Environment-Specific Overrides

Main environment files (`development.yaml`, `staging.yaml`, `production.yaml`) contain:
- Database connection settings
- External service URLs
- Resource limits
- Environment-specific feature flags

### 3. Environment Variable Overrides

Environment variables always take highest priority:
```bash
export DATABASE_HOST=custom-db.example.com
export API_WORKERS=8
export MLFLOW_TRACKING_URI=http://custom-mlflow:5000
```

## Examples

### API Configuration Loading

For `ENVIRONMENT=production`:

1. **Base API config** (`configs/api/base.yaml`):
```yaml
host: "0.0.0.0"
port: 8000
workers: 4
timeout: 30
```

2. **Production environment config** (`configs/production.yaml`):
```yaml
api:
  workers: 8          # Override base config
  timeout: 60         # Override base config
  cors_origins:
    - "https://app.company.com"
```

3. **Environment variables**:
```bash
export API_PORT=9000  # Override everything else
```

4. **Final result**:
```yaml
host: "0.0.0.0"       # From base
port: 9000            # From env var (highest priority)
workers: 8            # From production.yaml
timeout: 60           # From production.yaml
cors_origins:         # From production.yaml
  - "https://app.company.com"
```

### MLflow Configuration Loading

For `ENVIRONMENT=staging`:

1. **Base MLflow config** (`configs/mlflow/base.yaml`):
```yaml
tracking_server:
  host: "0.0.0.0"
  port: 5000
  workers: 4
experiments:
  auto_logging:
    enabled: true
```

2. **Staging environment config** (`configs/staging.yaml`):
```yaml
mlflow:
  tracking_uri: "http://staging-mlflow.company.com:5000"
  experiment_name: "fraud_detection_staging"
  tracking_server:
    workers: 2       # Override base config for staging
```

3. **Final result**:
```yaml
tracking_uri: "http://staging-mlflow.company.com:5000"  # From staging.yaml
experiment_name: "fraud_detection_staging"              # From staging.yaml
tracking_server:
  host: "0.0.0.0"    # From base
  port: 5000         # From base
  workers: 2         # From staging.yaml (overrides base)
experiments:
  auto_logging:
    enabled: true    # From base
```

## Benefits of This Approach

### ✅ **Clear Separation of Concerns**
- **Base configs**: Component defaults and feature definitions
- **Environment configs**: Environment-specific overrides only
- **Environment variables**: Runtime overrides

### ✅ **No Duplication**
- Component settings defined once in base configs
- Environment differences only specified in environment configs
- No need for `environments:` sections within component configs

### ✅ **Easy Maintenance**
- Change component defaults in one place (base configs)
- Environment-specific changes only in environment configs
- Clear override hierarchy

### ✅ **Flexible Deployment**
- Same base configs work across all environments
- Easy to add new environments
- Runtime configuration via environment variables

## Implementation Changes Needed

To implement this strategy, we should:

1. **Restructure component configs** to remove `environments:` sections
2. **Create base configs** for each component with environment-agnostic defaults
3. **Move environment-specific settings** to main environment configs
4. **Update configuration loading logic** to handle component-specific configs

## Configuration Access in Code

The application code remains the same:

```python
from src.utils.config import get_config

# Get full configuration for current environment
config = get_config()

# Access component-specific configuration
api_config = config.api
mlflow_config = config.mlflow
beam_config = config.beam  # Custom component config

# All environment-specific overrides are already applied
print(f"API workers: {config.api.workers}")
print(f"MLflow URI: {config.mlflow.tracking_uri}")
```

## Environment Variable Mapping

The system supports extensive environment variable mapping:

```bash
# Database
export DATABASE_HOST=db.company.com
export DATABASE_PORT=5432
export DATABASE_PASSWORD=secret

# API
export API_HOST=0.0.0.0
export API_PORT=8000
export API_WORKERS=4

# MLflow
export MLFLOW_TRACKING_URI=http://mlflow:5000
export MLFLOW_EXPERIMENT_NAME=my_experiment

# Monitoring
export PROMETHEUS_ENABLED=true
export LOG_LEVEL=INFO
```

This provides maximum flexibility for deployment scenarios like Docker, Kubernetes, or cloud platforms.