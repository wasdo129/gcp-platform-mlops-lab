# GKE operations lab

A three-week track for engineers familiar with Kubernetes, with 3–5 hours per week in `europe-west3`.

| Week | Exercise | Evidence to keep |
| --- | --- | --- |
| 1 | [GKE Standard vs Autopilot](docs/learning/gke-standard-vs-autopilot.md) and the [zonal CPU-only Standard lab](docs/learning/gke-practical-lab.md) | Project inventory, Pending Pod and autoscaler events, estimated cost, and cleanup verification |
| 2 | [Autopilot experiment outline](docs/learning/gke-standard-vs-autopilot.md#autopilot-experiment-outline) | Compare submitted and admitted resource requests, provisioning, and idle cost after workload removal |
| 3 | [NVIDIA GPU on GKE outline](docs/learning/gke-gpu.md) | Quota and capacity assessment, a CPU-only scheduling exercise, and a design for a future GPU environment |

Run the cluster experiments sequentially. The Standard guide starts with read-only checks. Get explicit approval before provisioning, deleting resources, changing IAM or enabling APIs. Keep the Free Trial billing account unchanged. Budget alerts do not cap spending.

The [foundation audit](docs/learning/gcp-foundation-audit.md) and [Terraform bootstrap and networking exercise](docs/learning/terraform-bootstrap-and-networking.md) document earlier work. The GKE exercises use `gcloud` and `kubectl`.
