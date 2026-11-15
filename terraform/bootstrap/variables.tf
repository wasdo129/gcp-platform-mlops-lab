variable "project_id" {
  description = "Google Cloud project ID that will own the state bucket."
  type        = string
}

variable "region" {
  description = "Region of the Terraform state bucket."
  type        = string
  default     = "europe-west3"
}
