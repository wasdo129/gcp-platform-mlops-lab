# Engineering rules

- Use infrastructure as code. Separate Terraform bootstrap from workload state, constrain provider versions explicitly, and track the provider lock file when Terraform is introduced.
- Scope IAM to required permissions and resources. Prefer Workload Identity Federation for CI and GKE workloads. Never create long-lived service account keys or hardcode credentials.
- Keep audit reports, Terraform state, real variable files, saved plans, and credentials out of Git. Review example files and diffs before publishing.
- Use official Google Cloud documentation for pricing, quota, and eligibility. Check project quotas, capacity constraints, trial eligibility, and pricing before proposing any deployment.
- Default to short-lived lab resources. Document recurring cost drivers and cleanup steps before creating anything. Treat the configured $20 and $300 monthly budgets as alerts. They do not cap spend.
- Get explicit approval before any cloud mutation, including enabling an API, changing IAM, or running `terraform apply` or `terraform destroy`. Never upgrade the billing account. Persistent paid resources, GPUs, and public exposure of administrative services require explicit approval and a documented reason.
- Document architectural decisions and verification steps. Keep Terraform readable and add files only as each exercise needs them.
- Write repository content and technical documentation in English. Explain and mentor in Russian. End each exercise with a learning check and wait for direction before advancing.
