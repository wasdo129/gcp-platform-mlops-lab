# Lab cost and cleanup

Budget **USD 0.18–0.23 gross per hour** for one Frankfurt node and about **USD 0.72–0.92 for a four-hour session**, before extras or credits. This is a planning range using $0.07–0.11/hour for the VM, $0.10/hour for GKE, about $0.006–0.01/hour for 40 GiB combined disks, and $0.005/hour for the node IPv4 address. Verify current Frankfurt on-demand rates in the calculator before each first deployment. Estimate from apply start to confirmed cleanup. Surge upgrades and transient default-pool creation can add compute and disks. [GKE pricing](https://cloud.google.com/kubernetes-engine/pricing), [VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose), [disk pricing](https://cloud.google.com/compute/disks-image-pricing), [network pricing](https://cloud.google.com/vpc/network-pricing).

| Component | Lifecycle and purpose | Cost and cleanup |
| --- | --- | --- |
| GKE management | Ephemeral control plane | Per cluster-hour. Run the backed-up lab teardown and verify cluster absence. |
| CPU node and boot disk | Ephemeral GKE worker, 2 vCPU and 8 GiB with 30 GiB balanced disk | VM runtime and provisioned disk size. Compare nodes, instance groups and disks with preflight after teardown. |
| External node IPv4 | Ephemeral public-source GitOps egress | Per IP-hour. Check addresses and instances after destroy. |
| CNPG, Argo CD and smoke Deployment | Ephemeral workloads share the same node. CNPG provisions a 10 GiB balanced disk | Verify the exact CSI disk handle after teardown. A detached database disk can outlive GKE and continue billing. |
| VPC, subnet and firewall | Ephemeral network boundaries | Network transfer can be billable. Confirm the VPC and generated firewall rules disappear. There is no NAT, load balancer or reserved address in this plan. |
| Cloud Logging and Monitoring | Ephemeral producers and metered Google services | Ingestion, retention, custom metrics and queries can incur charges. System collection is enabled. Avoid adding application logs or custom metrics without checking the cost. Inspect usage and retention if costs persist. |
| Terraform state GCS | Persistent state and locks | Storage, version history, operations and possible egress. Retain independently of the cluster. Review accumulated versions and soft-deleted objects before retiring the foundation. |
| Artifact GCS | Persistent dataset, checkpoint and artifact store for future phases | Stored bytes, operations, transfer and soft-delete retention are metered. Leave empty until Phase 3. Inventory live and soft-deleted objects when retiring the foundation. |

Eligible unused GKE free-tier credit is up to USD 74.40 per billing account per month for GKE management of zonal Standard and Autopilot clusters. If available, it lowers the estimate by $0.10/hour. Free Trial credits are separate, and credits and billing eligibility must be checked in the console. Budget notifications do not cap spending. No GPU is in scope. [Free Trial terms](https://docs.cloud.google.com/free/docs/free-cloud-features), [GCS pricing](https://cloud.google.com/storage/pricing), [observability pricing](https://cloud.google.com/stackdriver/pricing).

Use the [deployment runbook](../runbooks/lifecycle.md) for cleanup and explicit approval of any residual deletions. Remove the foundation only under a separate approved decommission plan after preserving recoverable state and artifacts.
