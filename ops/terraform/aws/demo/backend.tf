terraform {
  backend "s3" {
    bucket         = "rt-ml-platform-tf-state-prod"
    key            = "demo/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "rt-ml-platform-tf-locks"
    encrypt        = true
  }
}
