output "state_bucket_name" {
  description = "Bucket name to use in the workload's GCS backend configuration."
  value       = google_storage_bucket.tfstate.name
}
