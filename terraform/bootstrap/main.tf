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
  project = var.project_id
}

resource "google_storage_bucket" "tfstate" {
  name                        = "${var.project_id}-tfstate"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }
}
