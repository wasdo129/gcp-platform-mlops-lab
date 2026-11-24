variable "enable_serving_pool" {
  description = "Enable one temporary, tainted CPU node for Phase 5 serving."
  type        = bool
  default     = false
}

resource "google_container_node_pool" "serving" {
  count      = var.enable_serving_pool ? 1 : 0
  project    = local.project
  name       = "serving"
  location   = local.zone
  cluster    = google_container_cluster.lab.name
  node_count = 1

  lifecycle {
    precondition {
      condition     = var.allow_public_node_egress
      error_message = "Serving requires separately approved public node egress for the upstream image and model."
    }
  }

  network_config {
    enable_private_nodes = !var.allow_public_node_egress
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = "e2-standard-4"
    service_account = local.node_account
    disk_type       = "pd-balanced"
    disk_size_gb    = 30
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = { "llmops.workload" = "serving" }

    taint {
      key    = "llmops.workload"
      value  = "serving"
      effect = "NO_SCHEDULE"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot = true
    }
  }
}
