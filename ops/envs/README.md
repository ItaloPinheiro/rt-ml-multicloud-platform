# Environment Configuration Templates

This directory contains environment-specific configuration templates following industry best practices.

## Structure

```
envs/
├── .env.local       # Local development configuration
├── .env.staging     # Staging environment configuration
├── .env.production  # Production environment configuration
└── README.md        # This file
```

## Usage

### Local Development
```bash
# Copy local template to root .env
cp envs/.env.local .env

# Or use the helper script
./scripts/start-local.sh
```

### Staging Deployment
```bash
# Copy staging template and edit values
cp envs/.env.staging .env
vim .env  # Edit with your staging values
```

### Production Deployment
```bash
# Copy production template and edit values
cp envs/.env.production .env
vim .env  # Edit with your production values

# Use the production start script
./scripts/start-prod.sh
```

## Environment Files Best Practices

1. **Never commit `.env`** - Only templates in this directory are version controlled
2. **Use strong passwords** - Replace all `CHANGE_ME` values
3. **Environment-specific values** - Each environment should have distinct credentials
4. **Secrets management** - Consider using AWS Secrets Manager or GCP Secret Manager for production
5. **Variable naming** - Use UPPER_SNAKE_CASE for all environment variables

## Configuration Hierarchy

```
.env.example         # Base template with all possible variables
envs/.env.local      # Local overrides (pre-configured)
envs/.env.staging    # Staging overrides
envs/.env.production # Production overrides
.env                 # Active configuration (not in git)
```

## Key Differences

### Local
- Uses MinIO for S3 compatibility
- Redpanda instead of Kafka
- Debug mode enabled
- No authentication required

### Staging
- Real cloud services (S3/GCS)
- Kafka for messaging
- Moderate resource limits
- Basic authentication

### Production
- Full cloud integration
- High availability settings
- Strict resource limits
- Full authentication and encryption

## Security Notes

- Production passwords must be at least 16 characters
- Use different credentials for each environment
- Rotate credentials regularly
- Never use default passwords in staging/production
- Consider using environment-specific service accounts