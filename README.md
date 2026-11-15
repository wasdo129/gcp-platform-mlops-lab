# GCP Platform Engineering & MLOps Lab

Build a reproducible, cost-controlled Google Cloud platform and document the design and operational trade-offs as a Senior DevOps, SRE, and MLOps infrastructure portfolio project.

| Phase | Learning objectives |
| --- | --- |
| 1. Foundations | Inspect project hierarchy, IAM, APIs, quotas, VPCs, and existing workloads. Design Terraform state and a minimal network. |
| 2. Kubernetes platform | Compare GKE Standard and Autopilot. Use workload identity, Artifact Registry, GitHub Actions, Argo CD, and Cloud Observability. |
| 3. MLOps | Build CPU-based training and deployment workflows with Vertex AI, then compare managed model serving with GKE and KServe. |
| 4. Portfolio | Document architecture, operational runbooks, security decisions, cleanup, and cost estimates. |

Plan for roughly 12 weeks at 3–5 hours per week, with 60% of the time on platform engineering and 40% on MLOps. The preferred lab locations are `europe-west3` and `europe-west3-a`.

## First assignment

Open Google Cloud Shell in the existing project. From a Cloud Shell copy of this repository, run the following command with your lab project ID.

```bash
./scripts/gcp-audit.sh YOUR_PROJECT_ID europe-west3
```

The script prints the report path and a status for each check. Reports are stored beneath the Git-ignored `.audit/` directory. See the [Foundation Audit guide](docs/learning/gcp-foundation-audit.md) for setup, interpretation, troubleshooting, and the proposal for the next exercise.
