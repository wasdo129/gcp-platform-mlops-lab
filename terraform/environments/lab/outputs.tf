output "network_id" {
  description = "Resource ID of the custom-mode lab VPC."
  value       = google_compute_network.lab.id
}

output "subnet_id" {
  description = "Resource ID of the regional lab subnet."
  value       = google_compute_subnetwork.lab.id
}

output "subnet_cidr" {
  description = "Primary IPv4 CIDR of the lab subnet."
  value       = google_compute_subnetwork.lab.ip_cidr_range
}
