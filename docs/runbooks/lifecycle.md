# Controlled deployment and teardown

Run from the repository root. Keep a single operator and terminal per lab session. The scripts use a dedicated kubeconfig at `~/.llmops-lab/lab.kubeconfig` and keep the current default kubeconfig untouched.

## 1. Read-only preflight

Review the [architecture](../architecture/platform.md) and [cost estimate](../costs/lab.md). Verify Free Trial eligibility and available credits in Billing. Gather the following inventory with the intended authenticated gcloud user.

```bash
project=project-557b18ac-4cdc-4a40-b3e
zone=europe-west3-a
region=europe-west3
gcloud config get-value project
gcloud services list --enabled --project="$project"
gcloud compute networks subnets describe default --project="$project" --region="$region"
gcloud compute regions describe "$region" --project="$project" --format=json |
  jq '.quotas[] | select(.metric | IN("CPUS", "IN_USE_ADDRESSES", "SSD_TOTAL_GB", "NVIDIA_L4_GPUS"))'
gcloud compute machine-types describe e2-standard-2 --project="$project" --zone="$zone"
gcloud container clusters list --project="$project"
gcloud storage buckets list --project="$project"
gcloud compute disks list --project="$project"
gcloud compute forwarding-rules list --project="$project"
gcloud projects get-iam-policy "$project" --flatten='bindings[].members' \
  --filter="bindings.members:serviceAccount:gke-lab-nodes@$project.iam.gserviceaccount.com"
```

Ensure Compute, Kubernetes Engine, Storage and IAM APIs are available. Confirm regional CPU, external IPv4, Persistent Disk and GKE cluster quota. Quota does not establish zonal capacity. Inspect effective external IP organization policy and check permission to create VPCs, node pools and cluster resources and to use the dedicated node service account. The node account uses `roles/container.defaultNodeServiceAccount`. The administrator needs GKE DNS endpoint connection permissions, appropriate Kubernetes permissions and GCS permissions for state objects and locking. Do not add permissions or enable APIs without separate approval.

Verify Bash, jq, curl, Terraform 1.17.2, Helm, kubectl, gcloud and the GKE auth plugin. Docker is optional for cloud lifecycle. Publish the reviewed Git commit to the configured GitHub repository so the chart and Git sources are reachable. The provided bootstrap expects anonymous access to its Git source. Review a read-only deploy-key configuration before attempting a private repository. Never put tokens in Git or URL parameters.

On 21 November 2026, the read-only checks found no GKE clusters or GCS buckets in this project. Compute, GKE, Storage and IAM APIs were enabled. The node identity held the expected role. The region reported 200 CPUs, 8 in-use IPv4 addresses and 500 GB SSD quota with zero usage. The zone listed `e2-standard-2` and GKE Regular default `1.36.4-gke.2377000`. Project billing was enabled, the effective external IPv4 policy allowed all values, and the configured GitHub repository was public. Recheck Free Trial balance, effective policies and capacity before provisioning.

## 2. Create the persistent foundation once

Obtain explicit approval for the two GCS buckets. Inspect both their names and any previous local/external Terraform state. The active foundation uses `project-557b18ac-4cdc-4a40-b3e-llmops-tfstate` for state and `project-557b18ac-4cdc-4a40-b3e-ml-artifacts` for artifacts. The legacy bootstrap still refers to `project-557b18ac-4cdc-4a40-b3e-tfstate`. Read-only checks returned 404 for all three names at review time. If either active bucket now exists, stop and verify ownership and lineage before approving a plan. If a previous lab was applied to the legacy bucket, recover and migrate its state through a separately reviewed procedure before using these scripts. Do not initialize an empty backend over existing resources. Do not reuse an unknown bucket or operate the historical exercise roots against the same resources.

Use an existing Google Application Default Credentials session, or establish user ADC with `gcloud auth application-default login` as a separate local authentication step. The gcloud login and ADC can represent different identities. Verify both before proceeding.

```bash
umask 077
terraform -chdir=infra/terraform/foundation init -lockfile=readonly
terraform -chdir=infra/terraform/foundation plan -out=foundation.tfplan
# Review the saved plan. Execute only after approval.
terraform -chdir=infra/terraform/foundation apply foundation.tfplan
```

Keep the foundation root state and any saved plan in restricted storage. Back up the local foundation state to encrypted storage and remove the saved plan when it is no longer needed. The GKE root uses the resulting state bucket at prefix `llmops/gke-lab`. Daily teardown only operates that prefix. Both buckets use prevent_destroy and force_destroy=false. A separately reviewed foundation retirement must export or explicitly discard every object generation and account for soft-delete retention.

## 3. Start the CPU lab

Obtain explicit approval for the zonal GKE lab and the external IPv4 for node egress. If that egress is prohibited, stop and resolve the approved private egress design first. Ensure no other operator is holding the lab lock. Use the full published Git revision.

```bash
scripts/gke-up.sh --allow-public-node-egress "$(git rev-parse HEAD)"
```

Read the Terraform plan and type the displayed create token only after approval. On a fresh cluster, choose the empty database token if there is no recovery archive, or confirm the restore target. To explicitly select an archive, append its absolute path. Otherwise the script picks the latest matching UTC dump by filename on first initialization. During reruns Argo and the GKE resources converge, but the initialization marker prevents replay of a restore. If interrupted between restore and the marker, follow the recovery procedure and verify data first.

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
kubectl get nodes -o wide
kubectl -n argocd get applications
kubectl -n ml-platform get cluster,pods,pvc
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

Use `https://localhost:8080` for Argo CD. Handle the initial admin secret as sensitive. The database endpoint is `mlflow-postgres-rw.ml-platform.svc`. To enable MLflow after image and IAM approval, see the [Phase 3 runbook](mlflow.md). Startup verifies the database initialization gate before rolling out MLflow.

## 4. Back up and remove the lab

Stop workload controllers and clients that write to `mlflow`. Coordinate any administrators with privileged connections before running:

```bash
scripts/gke-down.sh
```

The quiesce confirmation sets PostgreSQL's database connection limit to zero and closes existing database sessions, rolling back their uncommitted transactions. The local lock serializes the four scripts on one Mac. It does not protect against a second host, ad hoc SQL, or superuser and background writes. Keep a single operator, stop writers and leave the gate closed until destroy completes. The script saves and validates a fresh local archive, prints its location and size, records the PVC disk handle, and shows a Terraform destroy plan. Type the destroy token only after explicit approval. A refused confirmation or a failed backup or plan leaves the database closed and cluster running. Reopen intentionally after verifying data integrity and cancellation of teardown.

After destroy, compare the independent cluster, network, address, disk and forwarding-rule inventories. Also verify node instance groups and firewall rules against the recorded baseline. GKE can leave the PostgreSQL disk behind even with reclaim policy Delete. After a verified archive and separate explicit cleanup approval, delete only the exact unattached disk matching the recorded CSI handle. [GKE retained disk behavior](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/persistent-volumes).

```bash
gcloud compute disks describe DISK_NAME --project="$project" --zone="$zone"
# Only after explicit approval and verification of the exact disk and archive:
gcloud compute disks delete DISK_NAME --project="$project" --zone="$zone"
```

## Troubleshooting and recovery

| Symptom | Investigate |
| --- | --- |
| Terraform plan or creation fails | Keep the foundation untouched. Inspect API access, quotas, IAM, and GKE operations. Resolve partial state before retrying. `gke-up.sh` refuses plans with replacements or updates. |
| DNS endpoint unavailable | Compare the cluster endpoint with the dedicated kubeconfig and verify the active gcloud account, GKE IAM, and Kubernetes RBAC. |
| ImagePullBackOff or Argo repository errors | Inspect Pod events, repo-server logs, Git revision visibility, node egress and upstream rate limits. |
| CNPG webhook timeout | Check Deployment endpoints, actual control-plane source range, and VPC TCP 9443. A server dry run must succeed before the PostgreSQL Application starts. |
| PVC Pending or Pod Pending | Inspect PVC events, StorageClass `standard-rwo`, zone, node allocatable memory, and disk or CPU quota. |
| Backup failed | Check the CNPG primary, Mac free space, kubeconfig, and exec transport. Retry after repair. Previous validated dumps remain available. |
| Restore failed | Review the archive and the error. The single SQL transaction should roll back on ordinary import errors. A disconnected client can leave commit status uncertain. Verify objects and expected rows before deciding whether to retry. |
| Interrupted lifecycle | Verify no other process is still executing and inspect cluster/state. If the Mac lock directory is stale, remove it with `rmdir ~/.llmops-lab/lifecycle.lock`. Refresh the Terraform plan. |

After a cancelled teardown or verified manual restore, validate the sentinel or application tables, then reopen if service is desired. Use the dedicated kubeconfig and inspect the context before issuing SQL.

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
kubectl config current-context
primary=$(kubectl -n ml-platform get cluster/mlflow-postgres -o jsonpath='{.status.currentPrimary}')
kubectl -n ml-platform exec "$primary" -c postgres -- psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres \
  -c 'ALTER DATABASE mlflow CONNECTION LIMIT -1'
```

If initial restore committed but initialization did not finish, verify the expected records and ownership before manually creating the `database-initialized` ConfigMap with the current CNPG UID and PostgreSQL identity, then reopen the database.

```bash
database_uid=$(kubectl -n ml-platform get cluster/mlflow-postgres -o jsonpath='{.metadata.uid}')
database_id=$(kubectl -n ml-platform exec "$primary" -c postgres -- psql -X -At -U postgres -d postgres \
  -c "SELECT system_identifier || ':' || oid FROM pg_control_system(), pg_database WHERE datname = 'mlflow'")
test -n "$database_uid" && test -n "$database_id" &&
  kubectl -n ml-platform create configmap database-initialized \
    --from-literal="clusterUID=$database_uid" --from-literal="databaseID=$database_id"
```

## Emergency teardown without a fresh backup

**Irreversible data loss is possible.** This procedure is outside the standard script. Use only after explicit approval that accepts loss of any data since the last tested archive. Inspect the last good dump, recover from the current primary or retained disk if possible, and record the specific recovery point and the reason for the override.

Initialize only `infra/terraform/gke-lab` with the state bucket and `llmops/gke-lab` prefix as in `scripts/lab-common.sh`. Verify the Terraform cluster ID, project, zone and every resource in a saved `terraform plan -destroy` for that root. After separate confirmation of the exact plan, use `terraform apply` with that saved plan and verify residual resources as above. Never run the emergency procedure against the foundation or historical Terraform roots.
