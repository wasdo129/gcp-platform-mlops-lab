terraform {
  backend "gcs" {
    bucket = "project-557b18ac-4cdc-4a40-b3e-tfstate"
    prefix = "environments/lab"
  }
}
