variable "project_id" {
  description = "Google Cloud project ID that will own the lab VPC."
  type        = string
}

variable "region" {
  description = "Region of the lab subnet."
  type        = string
  default     = "europe-west3"
}

variable "subnet_cidr" {
  description = "Primary IPv4 CIDR of the lab subnet."
  type        = string
  default     = "10.40.0.0/24"

  validation {
    condition     = can(cidrnetmask(var.subnet_cidr))
    error_message = "The subnet CIDR must be a valid IPv4 CIDR."
  }
}
