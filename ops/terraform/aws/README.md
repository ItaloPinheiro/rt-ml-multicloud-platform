# AWS Terraform Infrastructure

This directory contains Terraform configurations for deploying the RT ML Platform to AWS.

## Environments

### Demo Environment (Zero-Cost Focus)

Located in `demo/`. Designed for demonstrations and learning with minimal costs.

**Architecture:**
- Single EC2 Spot Instance (t3.micro/t3.small)
- K3s (lightweight Kubernetes)
- SQLite for MLflow metadata
- In-memory Redis
- Local EBS storage for artifacts

## Prerequisites

1. **AWS CLI configured**
   ```bash
   aws configure
   # Or set environment variables:
   export AWS_ACCESS_KEY_ID="your-key"
   export AWS_SECRET_ACCESS_KEY="your-secret"
   export AWS_DEFAULT_REGION="us-east-1"
   ```

   **Bash (AWS SSO):**
   If you are using AWS SSO, you may need to explicitly export credentials:

   ```bash
   # Authenticate first
   aws sso login

   # Export credentials to environment variables
   eval $(aws configure export-credentials --format env)
   ```

3. **Terraform installed** (v1.5+)
   ```bash
   # Windows (chocolatey)
   choco install terraform

   # macOS
   brew install terraform

   # Linux
   wget https://releases.hashicorp.com/terraform/1.7.0/terraform_1.7.0_linux_amd64.zip
   unzip terraform_1.7.0_linux_amd64.zip
   sudo mv terraform /usr/local/bin/
   ```

3. **SSH Key Pair in AWS**
   ```bash
   aws ec2 create-key-pair --key-name ml-demo-key --query 'KeyMaterial' --output text > ml-demo-key.pem
   chmod 400 ml-demo-key.pem
   ```

## Demo Deployment

### Step 1: Initialize Terraform

```bash
cd ops/terraform/aws/demo
terraform init
```

### Step 2: Configure Variables

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:
```hcl
# Required
key_name = "your-existing-key-name"

# Optional overrides
aws_region     = "us-east-1"
instance_type  = "t3.micro"  # t3.micro for Free Tier
environment    = "demo"
```

### Step 3: Review the Plan

```bash
terraform plan
```

### Step 4: Deploy

### Step 4: Deploy
It is best practice to generate a plan first:

```bash
# 1. Generate execution plan
terraform plan -out=tfplan

# 2. Apply the plan
terraform apply tfplan -no-color > terraform_apply.log 2>&1
```

### Step 5: Access the Demo

After deployment completes, you'll see outputs like:
```
instance_public_ip = "54.123.45.67"
mlflow_url         = "http://54.123.45.67:30500"
api_url            = "http://54.123.45.67:30800"
grafana_url        = "http://54.123.45.67:30300"
ssh_command        = "ssh -i your-key.pem ubuntu@54.123.45.67"
```

Wait 5-10 minutes for the instance to fully bootstrap, then access the URLs.

## 💰 Cost Breakdown

### AWS Free Tier Eligible (New Accounts - 12 Months)

| Resource | Free Tier | Monthly Cost After |
|----------|-----------|-------------------|
| EC2 t2.micro/t3.micro | 750 hrs/month | ~$8/month |
| EBS gp3 30GB | 30 GB/month | ~$2.40/month |
| Data Transfer | 100 GB/month | $0.09/GB |
| S3 | 5 GB | $0.023/GB |

### ⚠️ Unavoidable Costs

| Resource | Cost | Why |
|----------|------|-----|
| **Public IPv4** | ~$3.65/month | Required for SSH and web access. AWS charges $0.005/hr for public IPs since Feb 2024 |
| **Spot Interruption Risk** | Variable | Spot instances can be terminated with 2-min notice |

### Total Estimated Costs

| Scenario | Monthly Cost |
|----------|--------------|
| **Within Free Tier** | ~$3.65 (just IPv4) |
| **After Free Tier** | ~$10-15/month |
| **Using Spot (t3.small)** | ~$5-8/month |

## 🛑 Cleanup (STOP PAYING!)

### Destroy All Resources

```bash
cd ops/terraform/aws/demo
terraform destroy -auto-approve
```

This will:
1. Terminate the EC2 instance
2. Delete the EBS volume
3. Remove the security group
4. Release any Elastic IPs

### Verify Cleanup

```bash
# Check no instances running
aws ec2 describe-instances --filters "Name=tag:Environment,Values=demo" --query "Reservations[*].Instances[*].[InstanceId,State.Name]"

# Check no volumes
aws ec2 describe-volumes --filters "Name=tag:Environment,Values=demo"
```

### Alternative: Stop Instead of Destroy

If you want to pause the demo without losing data:

```bash
# Get instance ID from Terraform state
INSTANCE_ID=$(terraform output -raw instance_id)

# Stop instance (EBS preserved, no compute charges)
aws ec2 stop-instances --instance-ids $INSTANCE_ID
```

**Note:** Stopped instances still incur EBS storage charges (~$2.40/month for 30GB).

## Troubleshooting

### Instance Not Starting

```bash
# Check cloud-init logs
ssh -i your-key.pem ubuntu@<IP> "sudo cat /var/log/cloud-init-output.log"
```

### K3s Not Running

```bash
ssh -i your-key.pem ubuntu@<IP>
sudo systemctl status k3s
sudo journalctl -u k3s -f
```

### Pods Not Running

```bash
ssh -i your-key.pem ubuntu@<IP>
sudo k3s kubectl get pods -n ml-pipeline
sudo k3s kubectl describe pod <pod-name> -n ml-pipeline
```

## Security Notes

1. **SSH Access**: Security group allows SSH from `0.0.0.0/0` by default. For production, restrict to your IP.
2. **Web Access**: NodePorts are exposed publicly. Use for demo only.
3. **Secrets**: The demo uses default passwords. Change for any real usage.

## Next Steps

After validating the demo, consider:
1. Setting up proper DNS with Route53
2. Adding SSL/TLS with Let's Encrypt
3. Moving to the production environment with EKS
