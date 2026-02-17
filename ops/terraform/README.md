# Terraform Infrastructure

This directory contains Terraform configurations for multi-cloud deployment of the RT ML Platform.

## Directory Structure

```
ops/terraform/
├── aws/
│   ├── demo/                    # Near-Zero Cost demo environment
│   │   ├── main.tf             # Main infrastructure
│   │   ├── variables.tf        # Input variables
│   │   ├── outputs.tf          # Output values
│   │   ├── user-data.sh        # EC2 bootstrap script
│   │   └── terraform.tfvars.example
│   └── README.md               # Quick Reference (see docs for details)
└── README.md                   # This file
```

## Documentation

*   **[AWS Deployment Guide](../../docs/terraform/aws-guide.md):** Detailed deployment instructions for the AWS Demo environment.
*   **[Remote State & CI/CD Guide](../../docs/terraform/remote-state.md):** Setting up S3 backend and GitHub Actions pipeline.

## Quick Start

### AWS Demo

```bash
cd ops/terraform/aws/demo
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your SSH key name

terraform init
terraform plan
terraform apply
```

### Cleanup (Stop Paying!)

```bash
cd ops/terraform/aws/demo
terraform destroy -auto-approve
```
