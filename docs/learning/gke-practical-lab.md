# CPU-only GKE Standard lab

## Read-only inventory

Snapshot from 2026-11-17. Scope is project `project-557b18ac-4cdc-4a40-b3e`, region `europe-west3`, zone `europe-west3-a`. The active gcloud user has a direct `roles/owner` binding.

| Status | Finding |
| --- | --- |
| Existing | Compute and GKE APIs are enabled, as are Logging and Monitoring. Regular channel default in the target zone was `1.36.4-gke.2377000`. `e2-standard-2` is listed in that zone (2 vCPU, 8 GiB). |
| Existing | The auto-mode `default` VPC and regional `default` subnet (`10.156.0.0/20`) have an internet-gateway default route. The subnet has no secondary ranges and Private Google Access is disabled. Default ingress includes broad internal access from `10.128.0.0/9` and internet-wide SSH, RDP and ICMP. |
| Existing | Regional usage is zero against limits of 24 E2 vCPUs, 200 generic vCPUs, 24 instances, 500 GiB of SSD-class persistent disk quota and eight in-use external addresses. Global GPU quota is 0, despite regional L4 and T4 quota of one each. |
| Existing | Billing is linked and the visible billing account is open. The former state bucket is listed as soft-deleted, with hard deletion scheduled for 2026-11-22 at 20:10 UTC. The enabled Compute default node service account has no direct project IAM binding in the policy inspected. The GKE cluster service agent has its project role. |
| Missing | Project-wide GKE cluster and Compute VM inventories were empty, as were lists for managed instance groups, disks, reserved addresses, forwarding rules and Cloud Routers. The former VPC `gcp-mlops-lab` and subnet `gcp-mlops-subnet` were absent. The active GCS bucket and workload backend prefix returned HTTP 404. |
| Requires confirmation | Check remaining Free Trial credit, expiration and account type in Billing. The billing-link status does not show these values. Confirm mode eligibility, available GKE free-tier credit, node identity permissions, current prices and subnet impact before approval. Zone catalog availability and quota do not guarantee live VM capacity. |

The earlier Terraform lab's active resources are gone within the inventory scope. Soft-deleted storage may still incur storage charges until expiry. The new lab can reuse `default` with private nodes and a DNS-only control plane. Cluster creation can add a GKE-owned secondary Pod range and firewall rules and will enable Private Google Access on the existing subnet. Record the original subnet settings and include the changes and any approved rollback in the lab scope. [Soft delete](https://docs.cloud.google.com/storage/docs/soft-delete), [Network isolation troubleshooting](https://docs.cloud.google.com/kubernetes-engine/docs/troubleshooting/network-isolation)

### Terraform reconciliation

Bootstrap's current local state has zero resources. Its older local backup still refers to the deleted bucket. The workload configuration points at `gs://project-557b18ac-4cdc-4a40-b3e-tfstate/environments/lab`. The local `.terraform/terraform.tfstate` is backend metadata. The remote workload state is inaccessible through the active bucket, so its last contents and potential stale entries remain unverified.

Keep the existing state and backups private. If Terraform is needed again, first agree on whether historical recovery is necessary. Before the soft-delete deadline, consider approved recovery only if authoritative state is needed. Review the bucket and state object generations and recover to a controlled location, then compare resource addresses and IDs against current inventory. If a new lab needs Terraform later, use a fresh backend or prefix once the inventory and ownership are confirmed. Import only verified live resources intended for management. Review a plan before any apply or state reconciliation. Restoring the bucket, migrating state, and changing state each require approval.

## 1. Preflight and spending

Run in a dedicated Bash or Zsh shell. Check the active account before using the project.

```bash
PROJECT=project-557b18ac-4cdc-4a40-b3e
REGION=europe-west3
ZONE=europe-west3-a
CLUSTER=gke-standard-cpu-lab

gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud services list --enabled --project="$PROJECT" \
  --filter='config.name:(compute.googleapis.com container.googleapis.com logging.googleapis.com monitoring.googleapis.com)' \
  --format='value(config.name)'
gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)'
gcloud container clusters list --project="$PROJECT"
gcloud container get-server-config --project="$PROJECT" --zone="$ZONE" \
  --format=json | jq '.channels[] | select(.channel=="REGULAR")'
gcloud compute machine-types describe e2-standard-2 --project="$PROJECT" --zone="$ZONE"
gcloud compute regions describe "$REGION" --project="$PROJECT" --format=json |
  jq '.quotas[] | select(.metric | test("^(CPUS|E2_CPUS|INSTANCES|SSD_TOTAL_GB)$"))'
gcloud compute networks subnets describe default --project="$PROJECT" --region="$REGION"
gcloud compute firewall-rules list --project="$PROJECT"
gcloud compute routes list --project="$PROJECT" --filter='network:default'
gcloud iam service-accounts list --project="$PROJECT"
gcloud projects get-iam-policy "$PROJECT" --format='table(bindings.role,bindings.members)'
gke-gcloud-auth-plugin --version
kubectl version --client
```

The audited local CLI lacks the GKE auth plugin. Install it with `gcloud components install gke-gcloud-auth-plugin` if the CLI uses the component manager. The audited kubectl 1.34.1 is two minor versions behind the selected Regular default. Use a client within one minor version of the live control plane. [Kubernetes version skew](https://kubernetes.io/releases/version-skew-policy/)

Verify the operator can create, read and delete the cluster, update pool autoscaling, access the DNS endpoint (`container.clusters.connect`) and act as the chosen node service account (`iam.serviceAccounts.actAs`). Use IAM Policy Troubleshooter for effective permissions when direct bindings are insufficient. Verify the node identity has `roles/container.defaultNodeServiceAccount` or equivalent effective permissions and check the required GKE service agents for the target version. The audited default identity needs confirmation before use. Record an existing eligible identity as `NODE_SA`. Any identity creation or grant is a separate approval item. Verify available project capacity for two nodes (4 E2 vCPUs, two instances and 60 GiB of boot storage). [GKE node identity](https://docs.cloud.google.com/kubernetes-engine/security/configure-node-service-accounts), [Service agents](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/service-accounts), [DNS endpoint access](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/latest/network-isolation)

Check Billing for available Free Trial credit, expiry and account status. Trial terms exclude GPUs. Review the [Free Program terms](https://docs.cloud.google.com/free/docs/free-cloud-features) and [Google Cloud Pricing Calculator](https://cloud.google.com/products/calculator) for current eligibility and rates.

Published on-demand USD list rates for Frankfurt, checked 2026-11-17.

| Meter | Hourly estimate |
| --- | ---: |
| One `e2-standard-2` VM | $0.08634 |
| One 30 GiB zonal `pd-balanced` boot disk, at $0.000164384/GiB-hour | $0.00493 |
| Standard cluster management fee | $0.10000 per cluster |
| One-node lab | $0.19127 gross, or $0.09127 if the cluster fee is fully offset |
| Two-node scale-out | $0.28253 gross, or $0.18253 if the cluster fee is fully offset |

Two hours at two nodes would cost approximately $0.57 gross for VM, disk and cluster time. The GKE free-tier credit is up to $74.40 per month per billing account for eligible zonal Standard and Autopilot cluster fees. It applies to the management fee. The remaining Free Trial promotional balance is separate. The estimate assumes private nodes without billable external IPv4, on-demand capacity without commitments, and no additional logs, metrics, registry transfer or egress charges. Actual billable usage and credits can differ. [E2 rates](https://cloud.google.com/products/compute/pricing/general-purpose), [Disk rates](https://cloud.google.com/compute/disks-image-pricing), [GKE rates](https://cloud.google.com/kubernetes-engine/pricing)

Use the existing $20 and $300 budgets as alerts. They do not cap spending. Set a manual two-hour delete deadline before creation. Stop the exercise and begin approved cleanup if provisioning stalls or the second node cannot be acquired within the session.

## 2. Create after explicit approval

Approve creation, the limited scale-out and teardown before starting. Use Standard zonal mode, one on-demand COS node, Regular channel default, one 30 GiB balanced boot disk per node, node auto-repair and default channel-managed auto-upgrade. Use a one-node-at-a-time upgrade with zero surge because this is a disposable lab. Expect downtime on a single-node pool. Pool autoscaling and node auto-provisioning are initially disabled by omitting their enable flags. Use the default GKE Standard edition and leave optional paid GKE features disabled. Keep system metrics and short-lived system/workload logs, and disable Managed Service for Prometheus and HTTP Load Balancing. [Create flags](https://docs.cloud.google.com/sdk/gcloud/reference/container/clusters/create)

Explicitly set `NODE_SA` to the preflight-verified identity before running this block.

```bash
gcloud container clusters create "$CLUSTER" \
  --project="$PROJECT" --zone="$ZONE" --release-channel=regular \
  --machine-type=e2-standard-2 --num-nodes=1 --image-type=COS_CONTAINERD \
  --disk-type=pd-balanced --disk-size=30 --service-account="${NODE_SA:?Set the approved node identity}" \
  --network=default --subnetwork=default --enable-ip-alias \
  --enable-private-nodes --enable-dns-access --no-enable-ip-access \
  --enable-dataplane-v2 --workload-pool="$PROJECT.svc.id.goog" \
  --enable-autorepair --max-surge-upgrade=0 --max-unavailable-upgrade=1 \
  --logging=SYSTEM,WORKLOAD --monitoring=SYSTEM --no-enable-managed-prometheus \
  --addons=HttpLoadBalancing=DISABLED --labels=purpose=gke-cpu-lab
```

GKE allocates the Pod secondary range and uses its managed Service IPv4 range on the verified version. Dataplane V2 enforces NetworkPolicy when policies are present. GKE creates platform firewall rules alongside the pre-existing VPC rules. Private nodes have no public IPv4 address. Internal VPC reachability is still subject to firewall and NetworkPolicy. Private Google Access with the existing default route provides access to supported Google APIs and Artifact Registry. General internet egress from the nodes is unavailable without another egress path. The DNS control plane endpoint is reached through Google APIs and requires IAM and Kubernetes authorization. This configuration uses no Cloud NAT, application load balancer, PVC, accelerator or extra disk. [VPC-native addressing](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/alias-ips), [GKE firewall rules](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/firewall-rules), [Private Google Access](https://docs.cloud.google.com/vpc/docs/configure-private-google-access)

If creation returns an error, inspect GKE operations and the inventories in step 6. Provisioning may have made partial progress.

## 3. Connect and inspect

```bash
LAB_KUBE_DIR=$(mktemp -d)
export KUBECONFIG="$LAB_KUBE_DIR/config"
gcloud container clusters get-credentials "$CLUSTER" \
  --project="$PROJECT" --zone="$ZONE" --dns-endpoint

kubectl get nodes -o wide -L cloud.google.com/gke-nodepool,topology.kubernetes.io/zone
kubectl get pods -A -o wide
kubectl describe nodes
gcloud container node-pools list --cluster="$CLUSTER" --project="$PROJECT" --zone="$ZONE"
gcloud container clusters describe "$CLUSTER" --project="$PROJECT" --zone="$ZONE" \
  --format='yaml(tier,releaseChannel,currentMasterVersion,currentNodeVersion,controlPlaneEndpointsConfig,ipAllocationPolicy,networkConfig,privateClusterConfig,workloadIdentityConfig,loggingConfig,monitoringConfig,autoscaling,maintenancePolicy)'
gcloud container node-pools describe default-pool --cluster="$CLUSTER" \
  --project="$PROJECT" --zone="$ZONE" \
  --format='yaml(version,config.machineType,config.diskSizeGb,config.serviceAccount,config.workloadMetadataConfig,management,upgradeSettings,autoscaling,networkConfig)'
```

Record versions, upgrade settings and auto-repair configuration without issuing an upgrade. Verify the observed node has no external IP and compare allocatable CPU/memory with VM capacity.

## 4. Deploy and observe

Use a public sample hosted in Artifact Registry. Required hostname anti-affinity lets one replica run per node, so a second replica exposes the scheduler-to-Cluster-Autoscaler path with almost no actual CPU load.

```bash
kubectl apply -f - <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gke-cpu
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: gke-cpu
  template:
    metadata:
      labels:
        app: gke-cpu
    spec:
      automountServiceAccountToken: false
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: gke-cpu
              topologyKey: kubernetes.io/hostname
      containers:
        - name: hello
          image: us-docker.pkg.dev/google-samples/containers/gke/hello-app:1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 100m
              memory: 64Mi
            limits:
              cpu: 250m
              memory: 128Mi
YAML

kubectl -n default rollout status deployment/gke-cpu --timeout=120s
kubectl -n default get pods -l app=gke-cpu -o wide
kubectl -n default describe pods -l app=gke-cpu
kubectl -n default logs deployment/gke-cpu
kubectl -n default get events --sort-by=.lastTimestamp
gcloud logging read \
  "resource.type=\"k8s_container\" AND resource.labels.cluster_name=\"$CLUSTER\" AND labels.\"k8s-pod/app\"=\"gke-cpu\"" \
  --project="$PROJECT" --freshness=2h --limit=20
```

Optional: run `kubectl -n default port-forward deployment/gke-cpu 8080:8080` in one terminal and `curl -fsS http://127.0.0.1:8080/` in another. Stop port-forward after the request.

## 5. Bounded scale-out

After approval, start with autoscaling disabled. After scaling the Deployment, wait for the second Pod to show a FailedScheduling event citing anti-affinity before updating the pool. Enable pool autoscaling with a minimum of one and maximum of two. The pool has one zone, so the per-zone bounds also apply to the whole pool. No additional node pools can be auto-created by this experiment.

```bash
kubectl -n default scale deployment/gke-cpu --replicas=2
kubectl -n default describe pods -l app=gke-cpu
kubectl -n default get events --sort-by=.lastTimestamp

# Run after confirming the FailedScheduling event.
gcloud container clusters update "$CLUSTER" --project="$PROJECT" --zone="$ZONE" \
  --node-pool=default-pool --enable-autoscaling --min-nodes=1 --max-nodes=2
kubectl -n default rollout status deployment/gke-cpu --timeout=8m
kubectl -n default get pods -l app=gke-cpu -o wide
kubectl get nodes
gcloud logging read \
  "resource.type=\"k8s_cluster\" AND resource.labels.cluster_name=\"$CLUSTER\" AND log_id(\"container.googleapis.com/cluster-autoscaler-visibility\")" \
  --project="$PROJECT" --freshness=2h --limit=20

kubectl -n default scale deployment/gke-cpu --replicas=1
```

Compare scheduler events with the autoscaler's scale-up or refusal reason. Scale-down is asynchronous and depends on drainability and timers. If creation or scale-up stalls, check GKE operations, autoscaler visibility logs, Compute quota and zone capacity. Proceed to cleanup before the deadline even if scale-in has yet to occur. [Autoscaler visibility](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cluster-autoscaler-visibility)

## 6. Approved deletion and independent verification

```bash
gcloud container clusters delete "$CLUSTER" --project="$PROJECT" --zone="$ZONE"
```

Wait for deletion to complete. Compare the following independent inventories with the baseline, especially after a partial or failed operation.

```bash
gcloud container clusters list --project="$PROJECT"
gcloud container operations list --project="$PROJECT" --zone="$ZONE"
gcloud compute instance-groups managed list --project="$PROJECT"
gcloud compute instances list --project="$PROJECT"
gcloud compute disks list --project="$PROJECT"
gcloud compute addresses list --project="$PROJECT"
gcloud compute forwarding-rules list --project="$PROJECT"
gcloud compute routers list --project="$PROJECT"
gcloud compute firewall-rules list --project="$PROJECT"
gcloud compute networks subnets describe default --project="$PROJECT" --region="$REGION"
```

Check for lab-created MIGs, VMs, disks, addresses, load balancers, routers and GKE firewall rules. Check that GKE removed its allocated secondary range. Compare the Private Google Access setting with the preflight snapshot. If it was off and remains enabled, confirm no other workload uses it and restore it only with explicit approval.

```bash
gcloud compute networks subnets update default --project="$PROJECT" --region="$REGION" \
  --no-enable-private-ip-google-access
gcloud compute networks subnets describe default --project="$PROJECT" --region="$REGION"
```

Investigate any other verified lab-owned residue before separately approving resource-specific deletion. Check Billing Reports after reporting latency and inspect usage and credits separately. Remove the dedicated local kubeconfig when finished.

```bash
rm -f -- "$LAB_KUBE_DIR/config"
rmdir -- "$LAB_KUBE_DIR"
unset KUBECONFIG LAB_KUBE_DIR
```

Commands needing explicit approval include cluster create/delete, pool autoscaling changes, lab workload mutations as part of the approved session, subnet updates, and any IAM changes. Both required APIs are already enabled. If one is disabled in a future run, `gcloud services enable` requires separate approval. Terraform apply, destroy, state changes and billing upgrades are outside this lab.

Learning check: Explain which request or constraint made the second Pod Pending, what let GKE provision a node, and which meters kept running after scaling the Deployment down.
