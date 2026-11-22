terraform {
  required_version = "= 1.17.2"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.46.1"
    }
  }
}

provider "google" {
  project = local.project
}

resource "google_storage_bucket" "tfstate" {
  name                        = "${local.project}-llmops-tfstate"
  location                    = local.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  lifecycle {
    prevent_destroy = true
  }

  versioning {
    enabled = true
  }
}

locals {
  project = "project-557b18ac-4cdc-4a40-b3e"
  region  = "europe-west3"
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${local.project}-ml-artifacts"
  location                    = local.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  lifecycle {
    prevent_destroy = true
  }
}

output "state_bucket_name" {
  value = google_storage_bucket.tfstate.name
}

output "artifact_bucket_name" {
  value = google_storage_bucket.artifacts.name
}

resource "google_storage_bucket_iam_member" "mlflow_artifacts" {
  for_each = toset(["roles/storage.objectCreator", "roles/storage.objectViewer"])

  bucket = google_storage_bucket.artifacts.name
  role   = each.value
  member = "principal://iam.googleapis.com/projects/209948772676/locations/global/workloadIdentityPools/${local.project}.svc.id.goog/subject/ns/ml-platform/sa/mlflow"
}
