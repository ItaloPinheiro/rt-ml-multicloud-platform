# Live Configuration Patching Guide

This guide explains how to update the ML Pipeline API configuration in a running Kubernetes cluster without redeploying the entire application.

## Overview

Kubernetes ConfigMaps allow you to decouple configuration from container images. Changes to a ConfigMap can be applied live, and after restarting the affected pods, the new configuration takes effect without requiring a full redeployment.

## Prerequisites

*   `kubectl` configured to communicate with your cluster.
*   Access to the target namespace (e.g., `ml-pipeline-prod`).

## What Can Be Changed Live?

The following configurations in the `ml-pipeline-config` ConfigMap can be modified at runtime:

| Key | Default | Description | Restart Required? |
| :--- | :--- | :--- | :---: |
| `PRELOAD_MODELS` | `""` | Comma-separated list of `model_name:version` pairs to preload and track. Example: `fraud_detector:production,other_model:latest` | Yes |
| `MODEL_AUTO_UPDATE` | `"true"` | Enable/disable automatic model version polling. `"true"` or `"false"`. | Yes |
| `MODEL_UPDATE_INTERVAL` | `"60"` | Seconds between MLflow version checks. Lower values = faster updates, higher resource usage. | Yes |
| `LOG_LEVEL` | `"INFO"` | Application log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | Yes |
| `API_WORKERS` | `"4"` | Number of Uvicorn worker processes. | Yes |
| `BATCH_SIZE` | `"1000"` | Default batch size for batch predictions. | Yes |
| `FEATURE_STORE_TTL` | `"3600"` | Redis cache TTL for feature store entries (seconds). | Yes |
| `MODEL_CACHE_SIZE` | `"10"` | Maximum number of model versions to keep in memory. | Yes |

> **Note:** All ConfigMap changes require a pod restart to take effect because environment variables are injected at container startup.

## Patching Procedure

### Step 1: Create a Patch File

Create a JSON file with only the keys you want to modify.

```json
// patch.json
{
  "data": {
    "MODEL_UPDATE_INTERVAL": "10",
    "LOG_LEVEL": "DEBUG"
  }
}
```

### Step 2: Apply the Patch

Use `kubectl patch` with the `--patch-file` flag:

```bash
kubectl patch configmap ml-pipeline-config \
  -n ml-pipeline-prod \
  --type merge \
  --patch-file patch.json
```

**Expected Output:**
```
configmap/ml-pipeline-config patched
```

### Step 3: Restart the Pods

For the changes to take effect, restart the deployment:

```bash
kubectl rollout restart deployment ml-pipeline-api -n ml-pipeline-prod
```

### Step 4: Verify Rollout

Wait for the new pods to become ready:

```bash
kubectl rollout status deployment/ml-pipeline-api -n ml-pipeline-prod --timeout=120s
```

### Step 5: Confirm Changes

Check the running pod's environment to verify the new values:

```bash
kubectl exec -n ml-pipeline-prod deployment/ml-pipeline-api -- env | grep MODEL_UPDATE
```

## Example: Enable Faster Model Updates

To reduce the model update check interval from 60s to 10s for quicker iterations during development:

```json
// fast-updates-patch.json
{
  "data": {
    "MODEL_UPDATE_INTERVAL": "10"
  }
}
```

```bash
kubectl patch configmap ml-pipeline-config -n ml-pipeline-prod --type merge --patch-file fast-updates-patch.json
kubectl rollout restart deployment ml-pipeline-api -n ml-pipeline-prod
```

## Rollback

To revert a configuration change, simply apply a new patch with the original values:

```json
// rollback-patch.json
{
  "data": {
    "MODEL_UPDATE_INTERVAL": "60"
  }
}
```

```bash
kubectl patch configmap ml-pipeline-config -n ml-pipeline-prod --type merge --patch-file rollback-patch.json
kubectl rollout restart deployment ml-pipeline-api -n ml-pipeline-prod
```

## Secrets

Sensitive values (like `DATABASE_PASSWORD`, `REDIS_PASSWORD`) are stored in a **Secret**, not a ConfigMap. The patching procedure is identical, but you must use `kubectl patch secret` instead:

```bash
kubectl patch secret ml-pipeline-secrets -n ml-pipeline-prod --type merge --patch-file secret-patch.json
```

> ⚠️ **Warning:** Secret values must be base64-encoded in the patch file.

## Best Practices

1.  **Test in Non-Production First:** Always test configuration changes in a staging environment before applying to production.
2.  **Keep Patch Files:** Store your patch files in version control for auditability.
3.  **Use Descriptive Names:** Name your patch files descriptively (e.g., `enable-debug-logging.json`).
4.  **Monitor After Changes:** Watch logs and metrics after applying a patch to catch issues early.
