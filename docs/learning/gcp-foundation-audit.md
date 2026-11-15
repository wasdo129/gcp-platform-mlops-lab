# GCP Foundation Audit

Establish a baseline for one existing project. The audit reads project-level inventory and regional Compute Engine allocation quotas without provisioning cloud resources.

## Run in Google Cloud Shell

Open Cloud Shell as the authorized lab user. If a Git remote already contains the audit files, clone or update the repository in Cloud Shell. For an unpublished copy, create a source archive from the local repository root.

```bash
tar -czf /tmp/gcp-foundation-audit.tar.gz README.md AGENTS.md .gitignore docs/learning/gcp-foundation-audit.md scripts/gcp-audit.sh scripts/gcp-audit-report.py
```

Upload the archive through the Cloud Shell file menu and extract it in Cloud Shell. [Cloud Shell file transfers](https://docs.cloud.google.com/shell/docs/uploading-and-downloading-files)

```bash
mkdir -p ~/gcp-platform-mlops-lab
tar -xzf ~/gcp-foundation-audit.tar.gz -C ~/gcp-platform-mlops-lab
cd ~/gcp-platform-mlops-lab
```

From the repository root, replace `YOUR_PROJECT_ID` with the lab project ID. The explicit project argument scopes each cloud query independently of the active CLI configuration. The region argument scopes only the quota check. Subnets, VMs, and GKE clusters are listed across the project.

```bash
bash scripts/gcp-audit.sh YOUR_PROJECT_ID europe-west3
```

Read the `report.json` path printed by the script. Each invocation creates a private run directory beneath `.audit/`. Reports contain resource identifiers, service account addresses, and subnet ranges. Keep them private and redact infrastructure details before sharing excerpts. The report omits user and group identities, IAM condition text, VM metadata, cluster endpoints, and raw CLI errors.

## Interpret the report

| Section | What to inspect and why |
| --- | --- |
| `gcloud_config` | Compare the default project with the report target and check region and zone defaults. `account_configured` reflects the presence of a CLI setting. Successful cloud reads establish whether the identity can perform each check. |
| `project` | Confirm the project ID, number, and lifecycle state. A folder or organization parent is a cue to review inherited policy. |
| `enabled_apis` | Check Compute Engine, IAM, Cloud Storage, and Kubernetes Engine against the planned lab. An enabled API gives no evidence about existing workload usage, capacity, or trial eligibility. |
| `project_iam` | Review direct allow bindings for basic roles such as Owner and Editor, public principals, and unexpected service accounts. Conditional bindings require separate review of the condition. Effective access can also involve inherited grants, deny policies, and permissions attached to individual resources. |
| `service_accounts` | Compare workload identities and disabled accounts with direct IAM bindings. Identify broad grants to default or custom service accounts. The inventory does not assess key age, impersonation grants, or workload use. |
| `compute_quotas` | Compare each regional metric's `limit` and `usage`, especially CPU and persistent disk allocation. A regional quota is one constraint alongside global quotas, zone capacity, and Free Trial eligibility. |
| `vpc_networks` | Identify auto-mode networks, including a default network if one exists. Compare routing modes before deciding whether to reuse a VPC or create a dedicated custom-mode lab network. |
| `subnets` | Review primary and secondary IPv4 ranges for collisions with planned nodes, Pods, and Services. Check Private Google Access and account for peer or Shared VPC ranges beyond what this project lists. |
| `compute_instances` | Identify active machines, zone, and machine type. Stopped VMs may still have billable disks or addresses. |
| `gke_clusters` | Review location, status, Kubernetes control-plane version, and reported Autopilot mode. Include node or workload costs and attached resources when following up on an existing cluster. |

Project IAM, network, and quota references. [IAM inheritance](https://docs.cloud.google.com/iam/docs/resource-hierarchy-access-control), [Shared VPC](https://docs.cloud.google.com/vpc/docs/shared-vpc), [Compute Engine quotas](https://docs.cloud.google.com/compute/resource-usage), [Free Trial terms](https://docs.cloud.google.com/free/docs/free-cloud-features)

## Status and troubleshooting

- `ok` and `empty` mean the query succeeded. `empty` means the queried collection returned no results.
- `api_disabled` means the enabled API list excluded the required service or the API reported that it was disabled. If Service Usage is unavailable, the audit still attempts the independent reads.
- `permission_denied` means the result is unknown. Verify the lab identity and the exact read permission, such as `serviceusage.services.list`, `resourcemanager.projects.getIamPolicy`, or `container.clusters.list`, before requesting additional access.
- `authentication_required` calls for checking the current identity in Cloud Shell. Keep the output of `gcloud auth list` in your own terminal.
- `warning` means the command returned data alongside a diagnostic and inventory may be partial. For `not_found`, verify the target or region. For `timeout`, `invalid_output`, or `command_failed`, retry the corresponding read locally and inspect the CLI diagnostic there.

Exit status `0` means all checks finished with `ok` or `empty`. Status `2` means the report was saved with at least one unavailable section or warning. Status `1` means the invocation or report setup failed.

The audit provisions no billable resources. An empty inventory does not establish zero spend. Disks, load balancers, static addresses, logging, and storage are outside the audit. Review existing charges separately in Cloud Billing. Configured alert-only budgets send notifications without capping spend. [Cloud Billing budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets)

Cleanup is local. When the report is no longer needed, substitute its exact path below. No cloud cleanup is required.

```bash
rm -i -- .audit/RUN_DIRECTORY/report.json
rmdir -- .audit/RUN_DIRECTORY
```

## Proposed next lab

Plan a regional Cloud Storage backend bootstrap and a small custom-mode VPC with one subnet in `europe-west3`. Keep bootstrap and workload configurations separate. The GCS backend requires an existing bucket, supports state locking, and recommends object versioning for recovery. Compare storage operations and retained-version costs before seeking approval. [Terraform GCS backend](https://developer.hashicorp.com/terraform/language/backend/gcs)

- If the API inventory is complete and the required APIs are enabled, review IAM access for the bootstrap identity and use existing subnet ranges to choose a non-overlapping CIDR.
- If a Shared VPC or a suitable lab VPC already exists, verify delegated access and compare reuse with a new VPC. Review ownership before importing existing infrastructure.
- If API or IAM visibility is blocked, prepare a local `terraform init -backend=false` and `terraform validate` exercise. Use the report to identify the exact missing read or which API change would require approval.
- If Compute Engine quotas are exhausted or existing workloads show unexpected activity, resolve those findings before planning workloads. Keep the next design free of VMs, NAT, GKE, and GPUs.

## Interview and learning check

1. A project policy lists no direct binding for a principal that can create a VM. How would you trace the actual grant?
2. The GKE API is disabled, the Compute Engine regional CPU quota has headroom, and the preferred zone rejects VM creation. What would you verify first?
3. The VM and GKE inventories are empty but charges continue. Which resources and billing views would you use to narrow the source?
4. How would you recover Terraform state after an accidental overwrite, and what IAM access does recovery require?

Given the actual subnet inventory, explain whether you would reuse an existing VPC or build a custom-mode VPC for the lab. Identify which CIDR overlaps and access boundaries would change the decision.
