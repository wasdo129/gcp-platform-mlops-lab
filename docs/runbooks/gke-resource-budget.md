# Single-node Phase 4 resource budget

## Audit and budget

The 24 November 2026 read-only snapshot showed a single schedulable node with 1930m CPU, 6170212Ki memory and 110 pod slots. There were 26 non-terminal pods and no pod overhead or namespace LimitRange or ResourceQuota in `ml-platform`. Node memory, disk and PID pressure were false. The node used 290m CPU and 4912Mi memory. MLflow alone used 1878Mi against its 768Mi request and 2560Mi limit. These usage samples do not capture startup or reconciliation peaks.

| Scope | Current CPU requests | Proposed CPU requests | Configuration |
| --- | ---: | ---: | --- |
| kube-system | 740m | 740m | GKE-managed workloads |
| Argo CD Application Controller | 150m | 150m | Helm `controller.resources` |
| Argo CD Repo Server | 150m | 75m | Helm `repoServer.resources`, also inherited by `copyutil` |
| Argo CD Server | 100m | 50m | Helm `server.resources` |
| Argo CD ApplicationSet Controller | 75m | 25m | Helm `applicationSet.resources` |
| Argo CD Redis | 50m | 25m | Helm `redis.resources` |
| MLflow | 250m | 250m | `gitops/apps/mlflow/deployment.yaml` |
| PostgreSQL | 250m | 250m | `gitops/apps/cloudnative-pg/cluster.yaml` |
| CNPG operator | 100m | 100m | `gitops/applications/operator.yaml` Helm values |
| CPU Smoke | 50m | 10m | `gitops/apps/smoke/deployment.yaml` |

The Repo Server and PostgreSQL regular init containers each request the same CPU as their respective app container. The effective per-pod request uses their maximum. The GKE totals include the restartable init sidecars in `anetd` and `netd`. The Redis Helm hook is a separate transient Job with a 50m request. It is excluded from steady-state totals.

| State | CPU requests | CPU available for scheduling | Memory requests | Sum of declared memory limits |
| --- | ---: | ---: | ---: | ---: |
| Current | 1915m | 15m | 3647.5Mi | 6613Mi |
| With revised platform requests | 1675m | 255m | 3647.5Mi | 6613Mi |
| With one training Job | 1775m | 155m | 3967.5Mi | 7125Mi |

The changed services were using 1–4m CPU in the snapshot. The reduced requests give the single lab wider scheduling headroom while retaining CPU shares. Repo generation, reconciliation, API traffic and Redis bursts can use more CPU than the idle sample. Watch rollout duration and Argo health before accepting these lab settings. [Kubernetes effective requests](https://kubernetes.io/docs/concepts/resource-management/effective-pod-requests-limits/)

The 100m training request reserves CPU and provides a share under contention. The 500m limit bounds the workload's CPU consumption. The training container has a 320Mi request, 512Mi limit and single-thread settings for OpenMP and supported BLAS libraries. A local AMD64 run under Docker Desktop emulation recorded a cgroup peak of 285126656 bytes (272Mi), with zero OOM events under the 512Mi limit. The run took 29 seconds including startup and used about 14.2 CPU-seconds at 500m quota. It confirmed a finished run, two metrics and both artifacts against a temporary MLflow server with SQLite and a local artifact store. This is a baseline measurement. Native GKE timing and concurrent node memory can differ. Run one Job at a time. The node sample left about 1114Mi of allocatable memory unused, but that margin is not guaranteed. Relative to the sample, MLflow could grow another 682Mi while the Job could consume 512Mi, together exceeding the observed margin. Other workloads can also spike. Check node MemoryPressure, evictions and container OOMs. An OOM can occur at a container limit even when the node has free memory.

## Apply after review and explicit approval

Use a checkout of the reviewed, published Phase 4 commit. Keep the detached Phase 3 runtime worktree on its pinned revision. From the Phase 4 repo root, save the release values and GitOps revision. Confirm the installed chart is `argo-cd-10.17.2` and the intended changes are limited to the requests above. Verify live allocatable CPU and requests before each step. Stop if the namespace is unhealthy or the required CPU headroom is missing.

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
kubectl config current-context
helm -n argocd list --filter '^argocd$'
kubectl -n argocd get applications
kubectl describe node
reviewed_sha=$(git rev-parse HEAD)
test -z "$(git status --porcelain)"
test "$reviewed_sha" = "$(git ls-remote origin refs/heads/phase-4/training | cut -f1)"
old_smoke_sha=$(kubectl -n argocd get application cpu-smoke -o jsonpath='{.spec.source.targetRevision}')
umask 077
rollback_dir=$(mktemp -d)
helm -n argocd get values argocd -o yaml >"$rollback_dir/argo-values.yaml"
git show "$reviewed_sha:gitops/bootstrap/values.yaml" >"$rollback_dir/argo-reviewed.yaml"
```

Update CPU Smoke first. Its new 10m request fits the observed 15m headroom and releases 40m when the old pod exits. Wait for the old pod to terminate and verify at least 50m is free before Helm starts the pre-upgrade Redis Job. Do not submit training during these rollouts. CPU Smoke is the only Argo CD Application whose Git SHA changes here. Keep PostgreSQL, MLflow and the other Applications on their existing approved SHAs. The Helm values come from the same reviewed commit as CPU Smoke.

```bash
git show "$reviewed_sha:gitops/applications/cpu-smoke.yaml" |
  sed "s/@GIT_REVISION@/$reviewed_sha/g" | kubectl apply -f -
kubectl -n argocd wait --for=jsonpath='{.status.sync.revision}'="$reviewed_sha" \
  --for=jsonpath='{.status.sync.status}'=Synced \
  --for=jsonpath='{.status.health.status}'=Healthy application/cpu-smoke --timeout=5m
kubectl -n ml-platform rollout status deployment/cpu-smoke --timeout=3m
kubectl -n ml-platform get pods -l app=cpu-smoke
kubectl describe node
helm upgrade argocd argo-cd --repo https://argoproj.github.io/argo-helm \
  --version 10.17.2 -n argocd -f "$rollback_dir/argo-reviewed.yaml" --wait --timeout 10m
```

Check Argo CD reconciliation, CNPG and MLflow. Compare pod UIDs and restart counters before and after. Recheck memory and events while running one approved training Job. A low idle sample does not validate the limit under concurrent load.

```bash
kubectl -n argocd get applications
kubectl -n ml-platform get cluster,deploy,pods,pvc
kubectl -n ml-platform wait --for=condition=Ready cluster.postgresql.cnpg.io/mlflow-postgres --timeout=90s
kubectl -n ml-platform rollout status deployment/mlflow --timeout=90s
kubectl get pods -A
kubectl top node
kubectl -n ml-platform top pod --containers
kubectl -n ml-platform get events --sort-by=.lastTimestamp
```

## Rollback after approval

Wait for any training pod to exit and verify there is capacity for the 50m Helm hook. Reapply the saved values using the same chart version. A rolling rollback of repo-server can stall if a second 150m pod cannot fit. Use its chart-supported `Recreate` strategy for rollback so that Kubernetes releases the old request first. This can briefly interrupt manifest generation. Expect 55m of steady-state CPU headroom after restoring the original Helm requests while Smoke remains at 10m. Restore the old Smoke SHA last and confirm at least 50m is free for its replacement. If CPU headroom is still too small for a surge, leave Smoke on the reduced request until a separate maintenance window. Do not force replacement or recreate the cluster.

```bash
helm upgrade argocd argo-cd --repo https://argoproj.github.io/argo-helm \
  --version 10.17.2 -n argocd -f "$rollback_dir/argo-values.yaml" \
  --set repoServer.deploymentStrategy.type=Recreate --wait --timeout 10m
kubectl describe node
# If the old smoke pod cannot surge, defer this step.
git show "$reviewed_sha:gitops/applications/cpu-smoke.yaml" |
  sed "s/@GIT_REVISION@/$old_smoke_sha/g" | kubectl apply -f -
kubectl -n argocd wait --for=jsonpath='{.status.sync.revision}'="$old_smoke_sha" \
  --for=jsonpath='{.status.sync.status}'=Synced \
  --for=jsonpath='{.status.health.status}'=Healthy application/cpu-smoke --timeout=5m
kubectl -n ml-platform rollout status deployment/cpu-smoke --timeout=3m
```
