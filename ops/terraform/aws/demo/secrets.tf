resource "aws_secretsmanager_secret" "gh_pat_read" {
  name = "rt-ml-platform/gh-pat-read"
  description = "GitHub PAT read for pulling docker images"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "app_secrets" {
  name = "rt-ml-platform/app-secrets"
  description = "Application secrets for MLflow and Redis"
  recovery_window_in_days = 0
}
