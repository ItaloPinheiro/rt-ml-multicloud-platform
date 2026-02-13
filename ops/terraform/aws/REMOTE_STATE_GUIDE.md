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
