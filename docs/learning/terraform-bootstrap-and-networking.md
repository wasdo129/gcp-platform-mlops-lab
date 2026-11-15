# Lab 02. Terraform bootstrap and GCP networking

Use two Terraform root modules so the bucket can be managed independently of the network state it will eventually store. Both use Terraform `1.17.2`, the locked `hashicorp/google` provider `7.46.1`, and local state by default.

| Root | Terraform address | Planned resource |
| --- | --- | --- |
| `terraform/bootstrap` | `google_storage_bucket.tfstate` | `project-557b18ac-4cdc-4a40-b3e-tfstate`, regional Standard storage in Frankfurt. Object Versioning, uniform bucket-level access, and enforced public access prevention. |
| `terraform/environments/lab` | `google_compute_network.lab` | Global custom-mode VPC `gcp-mlops-lab` with regional dynamic routing. |
| `terraform/environments/lab` | `google_compute_subnetwork.lab` | Regional subnet `gcp-mlops-subnet` in `europe-west3` with primary CIDR `10.40.0.0/24` and Private Google Access. |

The project ID is required in both roots. Region defaults to `europe-west3`. The preferred zone `europe-west3-a` is available for future zonal resources. Private Google Access allows eligible workloads without external IPs to reach supported Google APIs when routing, DNS, and firewall policy permit it. The VPC creation keeps Google Cloud's default system-generated routes. [Private Google Access](https://docs.cloud.google.com/vpc/docs/private-google-access)

### Address plan

| Purpose | Range name | CIDR | Stage |
| --- | --- | --- | --- |
| Node and VM primary subnet range | `gcp-mlops-subnet` | `10.40.0.0/24` | Lab 02 |
| GKE Pods | `gke-pods` | `10.40.16.0/20` | Future secondary range |
| GKE Services | `gke-services` | `10.40.32.0/24` | Future secondary range |

The three ranges are pairwise disjoint and outside the auto-mode range `10.128.0.0/9`, including the existing Frankfurt subnet `10.156.0.0/20`. The existing `default` VPC is outside both root modules. Before adding secondary ranges, check routes and connected networks for overlap, then size the Pod range using the actual per-node Pod allocation and autoscaler limits. Size the Service range before cluster creation. [VPC auto-mode ranges](https://docs.cloud.google.com/vpc/docs/vpc), [GKE networking practices](https://docs.cloud.google.com/kubernetes-engine/docs/best-practices/networking)

## Local validation

From the repository root, use the committed provider locks.

```bash
terraform fmt -check -recursive terraform

terraform -chdir=terraform/bootstrap init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform/bootstrap validate

terraform -chdir=terraform/environments/lab init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform/environments/lab validate
```

Use existing Application Default Credentials (ADC) for plans or cloud operations. The Google provider and GCS backend discover ADC without credentials in Terraform files. The active `gcloud` CLI identity and ADC can differ. For a creation preview, use fresh copies of the two roots with no backend configuration or state. Run `terraform plan -refresh=false -input=false -var=project_id=project-557b18ac-4cdc-4a40-b3e` in each copy after initialization. This checks proposed resources against empty local state. It skips live inventory, API checks, IAM authorization, and global bucket-name availability. [Google Cloud Terraform authentication](https://docs.cloud.google.com/docs/terraform/authentication), [Terraform plan](https://developer.hashicorp.com/terraform/cli/commands/plan)

## Bootstrap state and bucket protection

The bootstrap root uses the default local backend. In the default workspace, Terraform writes bootstrap state to `terraform/bootstrap/terraform.tfstate` after the first apply. State, backups, and saved plans such as `terraform/bootstrap/bootstrap.tfplan` are ignored by Git. Keep saved plans private because they can contain state and other sensitive values. [Terraform local backend](https://developer.hashicorp.com/terraform/language/backend/local), [Terraform saved plans](https://developer.hashicorp.com/terraform/cli/commands/plan)

- `lifecycle.prevent_destroy = true` rejects Terraform plans to delete or replace the bucket while its resource block remains in the configuration. Removing the resource block removes this guard. Deletion through the console, CLI, or API is governed by Google Cloud IAM and bucket settings. [Terraform lifecycle rules](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle#prevent_destroy)
- The Google provider defaults to `deletion_policy = "DELETE"`. This permits a provider-side delete if Terraform reaches the delete operation and the bucket meets Cloud Storage's deletion requirements. The Terraform lifecycle guard acts earlier, during planning. [Google provider bucket settings](https://github.com/hashicorp/terraform-provider-google/blob/v7.46.1/website/docs/r/storage_bucket.html.markdown)
- `force_destroy = false` leaves object deletion to the operator. Live or noncurrent object generations can block bucket deletion. An empty bucket can still be deleted once the lifecycle guard is lifted and deletion is authorized. [Google provider bucket settings](https://github.com/hashicorp/terraform-provider-google/blob/v7.46.1/website/docs/r/storage_bucket.html.markdown)

### Soft-delete recommendation

Use **7 days (`604800` seconds)**, the minimum enabled retention. Object Versioning keeps prior state generations available for rollback. Soft delete provides an additional recovery window if someone deletes a specific generation or the bucket. Cloud Storage bills soft-deleted data until it expires, so longer retention adds cost. Noncurrent versions kept by Object Versioning have their own storage cost and do not expire under the soft-delete policy. [Cloud Storage soft delete](https://docs.cloud.google.com/storage/docs/soft-delete), [Object Versioning](https://docs.cloud.google.com/storage/docs/object-versioning), [Cloud Storage pricing](https://cloud.google.com/storage/pricing)

The current configuration omits `soft_delete_policy` and inherits the service-side value. Cloud Storage normally defaults to seven days. If the lab needs to enforce seven days regardless of a tagged project default, the provider setting is `soft_delete_policy { retention_duration_seconds = 604800 }`. Verify the effective value after the first authorized apply. [Cloud Storage defaults](https://docs.cloud.google.com/storage/docs/soft-delete), [Google provider soft-delete settings](https://github.com/hashicorp/terraform-provider-google/blob/v7.46.1/website/docs/r/storage_bucket.html.markdown)

## Future GCS backend migration

Use this procedure only after the bucket is created under separate approval. Before any deployment, confirm that the Cloud Storage and Compute Engine APIs are enabled, that the bucket name is globally available, and that the intended identities have the required permissions. Keep bucket administration separate from workload state access. The GCS backend needs object read, write, list, and delete permissions for state and locks. Scope the backend identity's `roles/storage.objectAdmin` grant to the state bucket as appropriate. [GCS backend permissions and locking](https://developer.hashicorp.com/terraform/language/backend/gcs)

1. Keep bootstrap state local and save an encrypted backup outside the repository. Avoid storing the bucket's only authoritative state in the bucket it manages.
2. Pause all workload state writers. If the workload root has local state, make a restrictive backup outside the checkout before adding backend configuration. For the default workspace:

   ```bash
   umask 077
   lab_state_backup=$(mktemp -d)
   terraform -chdir=terraform/environments/lab state pull > "$lab_state_backup/lab-before.tfstate"
   test -s "$lab_state_backup/lab-before.tfstate"
   ```

   Move the backup to protected storage if it is needed beyond the current session. If other workspaces exist, inventory and back up each state before migration.
3. Get the bucket name from `terraform -chdir=terraform/bootstrap output -raw state_bucket_name`. Confirm the destination prefix is empty or is already known to belong to this root. Add this block in `terraform/environments/lab/backend.tf`, using that bucket name:

   ```hcl
   terraform {
     backend "gcs" {
       bucket = "project-557b18ac-4cdc-4a40-b3e-tfstate"
       prefix = "terraform/lab"
     }
   }
   ```

4. If local state exists, run `terraform -chdir=terraform/environments/lab init -migrate-state` and review the copy prompt. For a fresh workload root, run `terraform -chdir=terraform/environments/lab init`. Backend migration can write state to GCS. Keep the same working directory and backend metadata while migrating.
5. For migrated state, compare remote `terraform state list` with the pre-migration addresses. Pull remote state into another private file and verify its lineage and serial against the backup. Review a plan before resuming writes. The default workspace object is `terraform/lab/default.tfstate`.

### Recover a previous state generation

1. Pause CI and human writers. Verify the correct bucket, prefix, workspace, and existing Terraform lock. Check that any apparent stale lock has no active owner.
2. Identify the target generation with `gcloud storage ls --all-versions "$state_object"`, where `state_object` is the complete `gs://...` URL of the workspace state. Download the current and candidate object generations to private files for inspection. Check Terraform state lineage, serial, and resource addresses against the intended recovery point and investigate any infrastructure changes since that generation.
3. With explicit approval, restore the candidate as a new live generation. Set `good_generation` to the selected version and `live_generation` to the current live object's generation, or `0` if it is missing. The precondition stops the copy if the live object has changed since inspection:

   ```bash
   gcloud storage cp --if-generation-match="$live_generation" \
     "${state_object}#${good_generation}" "$state_object"
   ```

4. Verify the recovered addresses with `terraform state list` and compare a fresh plan to live infrastructure before any apply. Recovering state changes Terraform's inventory. It does not roll back resources. If the bucket or the required generation is soft-deleted, follow the Cloud Storage soft-delete procedure first. [Versioned object recovery](https://docs.cloud.google.com/storage/docs/using-versioned-objects), [Cloud Storage soft delete](https://docs.cloud.google.com/storage/docs/soft-delete)

## Cost and cleanup

- The idle VPC, subnet, and Private Google Access setting have no expected recurring charge in this configuration. Traffic and services used by future workloads are separate costs. [VPC pricing](https://cloud.google.com/vpc/network-pricing)
- For the bucket, a planning example with 100 MiB across all retained versions including soft-deleted objects, 100 Class A requests, and 1,000 Class B requests per month is about **USD 0.005/month** before transfer and tax. It uses illustrative rates of USD 0.03/GiB-month, USD 0.01 per 1,000 Class A requests, and USD 0.001 per 1,000 Class B requests. Check Frankfurt pricing before deployment. [Cloud Storage pricing](https://cloud.google.com/storage/pricing)

This lab stops at local validation. If the resources are deployed later, remove them in this order under separate approval:

1. Freeze workload writers and back up both states. Review a workload destroy plan and remove the subnet and VPC while the workload backend is available. Verify the plan targets the lab VPC and subnet, and verify deletion before moving on.
2. Confirm no other root or workspace uses the bucket. Preserve final state snapshots. If retaining the workload root, migrate its state back to local by removing its GCS backend block and running `init -migrate-state` in the initialized working directory. Verify the destination before decommissioning the bucket.
3. Inspect the bucket's live and noncurrent object generations, including any lock files, and remove only approved objects after confirming the backups. For approved decommissioning, retain the resource block, remove the `prevent_destroy` guard in the reviewed change, and review the resulting bootstrap destroy plan before deleting the bucket last. Leave `force_destroy = false` in place. Account for any remaining soft-delete retention.

### Learning check

Why should the workload be cleaned up before the state bucket, and how would you verify that restoring an older state version has preserved ownership of the live subnet?
