resource "google_artifact_registry_repository" "llmops_images" {
  project       = local.project
  location      = local.region
  repository_id = "llmops-images"
  description   = "Docker images for the LLMOps lab"
  format        = "DOCKER"
  mode          = "STANDARD_REPOSITORY"
}

resource "google_artifact_registry_repository_iam_member" "gke_node_reader" {
  project    = google_artifact_registry_repository.llmops_images.project
  location   = google_artifact_registry_repository.llmops_images.location
  repository = google_artifact_registry_repository.llmops_images.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:gke-lab-nodes@${local.project}.iam.gserviceaccount.com"
}

output "artifact_registry_repository_name" {
  description = "Name of the Docker repository used by the lab."
  value       = google_artifact_registry_repository.llmops_images.repository_id
}

output "artifact_registry_repository_url" {
  description = "Docker repository prefix without an image name or tag."
  value       = "${local.region}-docker.pkg.dev/${local.project}/${google_artifact_registry_repository.llmops_images.repository_id}"
}
