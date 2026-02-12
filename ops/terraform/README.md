# Terraform Infrastructure

This directory contains Terraform configurations for multi-cloud deployment of the RT ML Platform.

## Directory Structure

```
ops/terraform/
├── aws/
│   ├── demo/                    # Zero-cost demo environment
│   │   ├── main.tf             # Main infrastructure
│   │   ├── variables.tf        # Input variables
│   │   ├── outputs.tf          # Output values
│   │   ├── user-data.sh        # EC2 bootstrap script
│   │   └── terraform.tfvars.example
│   └── README.md               # AWS-specific documentation
└── README.md                   # This file
```

## Quick Start

### AWS Demo (Zero-Cost)

```bash
cd ops/terraform/aws/demo
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your SSH key name

terraform init
terraform plan
terraform apply
terraform apply
```

### Cleanup (Stop Paying!)

```bash
cd ops/terraform/aws/demo
terraform destroy -auto-approve
```

## Cost Summary

| Environment | Monthly Cost | Notes |
|-------------|--------------|-------|
| **Demo** | $6-10/month | Mostly Free Tier eligible |
| **Production** | ~$200+/month | EKS + RDS + ElastiCache |

See [aws/README.md](./aws/README.md) for detailed cost breakdown.
