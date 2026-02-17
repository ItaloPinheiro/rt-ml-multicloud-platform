# Remote State & CI/CD Setup Guide

This guide explains how to transition from local state to a robust Remote State setup with AWS S3 + DynamoDB, and how to enable the Continuous Deployment pipeline.

## Phase 1: One-Time Bootstrap (Manual)

**Goal:** Create the S3 bucket and DynamoDB table to store Terraform state securely.

1. **Navigate to the Bootstrap Directory**
   ```bash
   cd ops/terraform/aws/bootstrap
   ```

2. **Initialize and Apply**
   ```bash
   terraform init
   terraform apply
   ```
   *You will be prompted for a `unique_suffix` (e.g., `company-prod-001`) to ensure the S3 bucket name is globally unique.*

3. **Note the Outputs**
   After the apply finishes, you will see:
   ```hcl
   s3_bucket_name      = "rt-ml-platform-tf-state"
   dynamodb_table_name = "rt-ml-platform-tf-locks"
   ```
   *Copy these values.*

4. **Verify Creation**
   Check the AWS Console (S3 and DynamoDB) to confirm resources exist.

---

## Phase 2: Configure Demo Environment

**Goal:** Tell the Demo environment to use the new remote backend.

1. **Navigate to Demo Directory**
   ```bash
   cd ops/terraform/aws/demo
   ```

2. **Create Backend Configuration**
   Copy the example and edit it:
   ```bash
   cp backend.tf.example backend.tf
   ```

3. **Edit `backend.tf`**
   Update the `bucket` and `dynamodb_table` values with the outputs from Phase 1.
   ```hcl
   terraform {
     backend "s3" {
       bucket         = "rt-ml-platform-tf-state-company-prod-001" # <--- UPDATE THIS
       key            = "demo/terraform.tfstate"
       region         = "us-east-1"
       dynamodb_table = "rt-ml-platform-tf-locks"                  # <--- UPDATE THIS
       encrypt        = true
     }
   }
   ```

4. **Migrate State**
   Initialize Terraform again. It will detect the new backend and ask to migrate any existing local state.
   ```bash
   terraform init
   # Type 'yes' when prompted
   ```

---

## Phase 3: Configure GitHub Actions (CI/CD)

**Goal:** Enable the automated pipeline to plan and apply changes.

1. **Go to GitHub Repository Settings**
   `Settings` > `Secrets and variables` > `Actions`

2. **Add Repository Secrets**
   Use `New repository secret` to add:
   *   `AWS_ACCESS_KEY_ID`: Your AWS Access Key
   *   `AWS_SECRET_ACCESS_KEY`: Your AWS Secret Key
   *   `AWS_KEY_NAME`: The name of your EC2 Key Pair (e.g., `ml-pipeline-key`)

3. **Enable Deployments (Variables)**
   Go to `Variables` tab and create:
   *   `ENABLE_PRODUCTION_DEPLOY`: `true` (This controls if the CD workflow actually runs the apply step)

---

## Day-to-Day Workflow
 
Once the remote backend is configured, your local Terraform commaands will automatically sync with the S3 state.
 
### 1. Initialize (First Time Only)
Ensure your local directory is configured to use the S3 backend.
```bash
terraform init
```
*   This downloads the provider plugins and configures the backend.
*   It does **not** change any infrastructure.
 
### 2. Verify State (ReadOnly)
To check what Terraform thinks is the current state of the world (from S3) vs. your local code:
```bash
terraform plan
```
*   **No Changes:** If it says "No changes", your local code matches the remote infrastructure.
*   **Changes:** If it lists changes, it means either:
    *   You modified local code.
    *   Someone else updated the infrastructure (and the remote state).
 
### 3. Sync State (Refresh)
If you suspect the state file is out of sync with *actual* AWS resources (e.g., someone manually deleted an EC2 instance), use:
```bash
terraform refresh
```
*   This updates the `terraform.tfstate` in S3 to match reality.
*   **Warning:** It does not modify resources, only the state file.
 
### 4. Deploying Changes
**Recommended:** Push your changes to GitHub and let the CI/CD pipeline handle the `apply`.
 
**Emergency (Manual Apply):**
If you must apply locally (bypassing CI/CD), ensure you pull the latest code first.
```bash
git pull origin main
terraform apply
```
 
> [!WARNING]
> **State Locking:** Terraform automatically locks the DynamoDB table during operations. If you run `apply` locally while the CI/CD pipeline is running, one will fail with a "Lock Error". Wait for it to finish.
 
---
 
 ## Workflow Summary

### **1. Pull Request (CI Check)**
*   When you open a PR modifying `ops/terraform/**`, the **Terraform Plan** job runs.
*   It validates syntax and runs `terraform plan`.
*   The output shows what *would* happen (e.g., "Plan: 1 to add, 0 to change").
*   **Result:** You see if your changes are valid and safe before merging.

### **2. Merge to Main (CD Apply)**
*   When the PR is merged to `main`, the **Terraform Apply** job runs.
*   It runs `terraform apply -auto-approve` using the remote state.
*   **Result:** The infrastructure is actually updated in AWS.

## Troubleshooting

*   **Lock Error:** If a job fails saying "Error acquiring the state lock", check the DynamoDB table `rt-ml-platform-tf-locks`. If a previous job crashed, manually delete the lock item (after verifying no other process is running).
*   **Auth Error:** Verify `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are correct in GitHub Secrets.
