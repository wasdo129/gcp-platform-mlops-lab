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
  region  = local.region
}

resource "google_compute_network" "lab" {
  name                    = "llmops-lab"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "lab" {
  name                     = "llmops-lab"
  region                   = local.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.40.0.0/24"
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "gke-pods"
    ip_cidr_range = "10.44.0.0/16"
  }

  secondary_ip_range {
    range_name    = "gke-services"
    ip_cidr_range = "10.45.0.0/20"
  }
}

locals {
  project      = "project-557b18ac-4cdc-4a40-b3e"
  region       = "europe-west3"
  zone         = "europe-west3-a"
  cluster      = "llmops-lab"
  node_account = "gke-lab-nodes@${local.project}.iam.gserviceaccount.com"
  master_cidr  = "10.46.0.0/28"
}

variable "allow_public_node_egress" {
  description = "Use one ephemeral external IPv4 address per node for direct GitHub and public registry egress."
  type        = bool
  default     = false
}

resource "google_container_cluster" "lab" {
  name                     = local.cluster
  location                 = local.zone
  network                  = google_compute_network.lab.id
  subnetwork               = google_compute_subnetwork.lab.id
  networking_mode          = "VPC_NATIVE"
  datapath_provider        = "ADVANCED_DATAPATH"
  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false
  resource_labels          = { lab = "llmops" }

  node_config {
    machine_type    = "e2-standard-2"
    service_account = local.node_account
    disk_type       = "pd-balanced"
    disk_size_gb    = 30
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  release_channel {
    channel = "REGULAR"
  }

  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic = true
    }
    ip_endpoints_config {
      enabled = false
    }
  }

  private_cluster_config {
    enable_private_nodes   = true
    master_ipv4_cidr_block = local.master_cidr
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "gke-pods"
    services_secondary_range_name = "gke-services"
  }

  workload_identity_config {
    workload_pool = "${local.project}.svc.id.goog"
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS"]
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus {
      enabled = false
    }
  }
}

resource "google_container_node_pool" "cpu" {
  name       = "cpu"
  location   = local.zone
  cluster    = google_container_cluster.lab.name
  node_count = 1

  network_config {
    enable_private_nodes = !var.allow_public_node_egress
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = "e2-standard-2"
    service_account = local.node_account
    disk_type       = "pd-balanced"
    disk_size_gb    = 30
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    tags            = ["llmops-lab-node"]
    labels          = { lab = "llmops" }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot = true
    }
  }
}

resource "google_compute_firewall" "cnpg_webhook" {
  name          = "llmops-lab-cnpg-webhook"
  network       = google_compute_network.lab.id
  source_ranges = [local.master_cidr]
  target_tags   = ["llmops-lab-node"]

  allow {
    protocol = "tcp"
    ports    = ["9443"]
  }
}

output "cluster_id" {
  value = google_container_cluster.lab.id
}
