# Phase 5.1 Qwen3 CPU serving

## Local baseline after download approval

The pinned [model lock](../../gitops/charts/qwen-serving/files/model-lock.json) contains the Apache-2.0 license, revision, sizes and SHA-256 hashes. The two weight hashes and tokenizer JSON hash come from Hugging Face LFS metadata. Hashes for the remaining configuration and license files were computed from the exact upstream revision. Total download is 4,079,434,577 bytes (3.80 GiB), excluding dependencies. Keep the snapshot and reports outside the checkout.

The Mac preflight showed ARM64, 10 logical CPUs, 16 GiB RAM and 59 GiB free disk. The macOS memory-pressure command reported 62% system-wide free memory, about 10 GiB as a rough indicator. Recheck before loading FP32. Inspect the pressure level and swap as well as the free percentage. For the initial 16 GiB Mac run require normal pressure, no swap use and about 10 GiB available by this estimate. The index lists 4,063,479,808 bytes of stored tensors, or up to 7.57 GiB when all are widened to FP32. The loader maps safetensors shards and converts tensors serially, which avoids requiring an extra anonymous copy of the complete BF16 checkpoint. Mapped pages, temporary tensors and framework overhead can still raise the peak. Stop if the preflight fails or pressure rises. Use native macOS ARM64 Python 3.11 with the pinned dependency versions. Capture the resolved environment with the benchmark report.

```bash
memory_pressure -Q
sysctl kern.memorystatus_vm_pressure_level vm.swapusage
df -h . /tmp
run_dir=$(mktemp -d /tmp/qwen-baseline.XXXXXXXX)
python3.11 -m venv "$run_dir/venv"
py="$run_dir/venv/bin/python"
"$py" -m pip install -r apps/qwen-baseline/requirements.txt
"$py" -m pip freeze > "$run_dir/requirements-resolved.txt"
"$py" gitops/charts/qwen-serving/files/model_snapshot.py \
  gitops/charts/qwen-serving/files/model-lock.json "$run_dir/model"
HF_HUB_OFFLINE=1 HF_ENABLE_PARALLEL_LOADING=false "$py" apps/qwen-baseline/benchmark.py "$run_dir/model" |
  tee "$run_dir/benchmark.json"
```

Run in a shell with `set -o pipefail`. The report separates model loading, tokenization and generation. TTFT is the first generated token callback, excluding tokenization. Peak RSS is the whole Python process, including model load. ARM64 memory bandwidth, kernels and variable cache warmth differ from GCE AMD64. The local numbers establish a reference for correctness and observation, with native GCE qualification required for sizing.

## CPU qualification gate

The upstream vLLM 0.34.0 CPU image is pinned in chart values. Registry metadata confirmed `linux/amd64` and entrypoint `vllm serve`. No custom build is planned unless the verified upstream image fails a target requirement. vLLM documents Linux AVX2 with limited functionality and recommends AVX-512F. Linux Arm needs NEON and Apple Silicon CPU support is experimental. E2 host selection can vary. Check the allocated node's actual flags and image behavior, then confirm BF16, `--kv-cache-memory-bytes`, `nobind`, warm-up and restrictive security context on native AMD64. Inspect the CLI help and logs; ARM64 emulation is insufficient. If the upstream image needs additional capabilities or a different machine, stop for review. [Pinned vLLM CPU documentation](https://docs.vllm.ai/en/v0.34.0/getting_started/installation/cpu/)

## Temporary pool, after separate infrastructure approval

Use a reviewed checkout with the existing GCS backend and default workspace. Use the shared lifecycle lock and one operator to serialize approval, planning and application. Keep the platform provisioned with its current node egress setting. Verify the remote state cluster ID and inspect the live pool list before proceeding. For creation, ensure there is no existing `serving` pool in GKE or duplicate state. For removal, first complete application cleanup below and verify that no user workload remains scheduled on the pool. Use `mode=create` for creation or `mode=delete` for removal. The delete is a normal plan with the feature disabled. Neither operation targets the platform pool.

```bash
(
  set -euo pipefail
  source scripts/lab-common.sh
  check_project
  check_terraform
  begin_lifecycle
  check_target
  init_lab_backend
  test "$(tf output -raw cluster_id)" = "$CLUSTER_ID"

  mode=create
  # For removal after workload cleanup, use mode=delete.
  case "$mode" in
    create) enabled=true ;;
    delete)
      enabled=false
      test -z "$(k -n argocd get application qwen-serving --ignore-not-found -o name)"
      k get deployment,service,pods -A -o json |
        jq -e 'all(.items[]; .metadata.namespace != "llm-serving")'
      serving_nodes=$(k get nodes -l cloud.google.com/gke-nodepool=serving -o json |
        jq -c '[.items[].metadata.name]')
      k get pods -A -o json | jq -e --argjson nodes "$serving_nodes" '
        all(.items[]; (.spec.nodeName as $node | $nodes | index($node)) == null
          or any(.metadata.ownerReferences[]?; .kind == "DaemonSet"))
      '
      ;;
    *) die "Invalid pool operation" ;;
  esac

  plan="$WORK_DIR/serving.tfplan"
  tf plan -input=false -lock-timeout=30s -var=allow_public_node_egress=true \
    -var="enable_serving_pool=$enabled" -out="$plan"
  tf show -json "$plan" | jq -e --arg operation "$mode" '
    [.resource_changes[]? | select(.mode == "managed" and .change.actions != ["no-op"])]
    | length == 1 and .[0].address == "google_container_node_pool.serving[0]"
    and .[0].change.actions == [$operation]
  '
  tf show -no-color "$plan"
  confirm "$mode $PROJECT/$ZONE/$CLUSTER/serving"
  tf apply -input=false -lock-timeout=30s "$plan"
)
```

Confirm that the platform pool identity and settings are unchanged, the dedicated labels and taint match the chart, and PostgreSQL and MLflow Pod UIDs and counters are unchanged. The serving pool has one node and no autoscaling. Delete it when the experiment ends. The platform up script sets the feature false explicitly and rejects deletion plans. The down script stops before PostgreSQL or MLflow changes if either state or GKE still contains this pool. The full-cluster destructive allowlist stays unchanged. Use the reviewed checkout containing these guards for lifecycle operations.

## GitOps serving, after separate rollout approval

From a reviewed checkout, verify a full Git SHA reachable from published `origin/main`. The standalone Application uses manual sync. Confirm the target node has at least 2500m CPU and 9 GiB measured memory headroom plus disk space for the image and 12 GiB model cache. Record current App health, MLflow/PostgreSQL UIDs, restart counts and node pressure before syncing.

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
reviewed_sha=$(git rev-parse HEAD)
git fetch origin main
git merge-base --is-ancestor "$reviewed_sha" origin/main
git show "$reviewed_sha:gitops/applications/qwen-serving.yaml" |
  sed "s/@GIT_REVISION@/$reviewed_sha/g" | kubectl apply -f -
# From an authenticated Argo CD CLI session:
argocd app sync qwen-serving --revision "$reviewed_sha" --timeout 1800
kubectl -n llm-serving rollout status deployment/qwen-serving --timeout=30m
kubectl -n llm-serving port-forward --address 127.0.0.1 service/qwen-serving 18000:8000
```

In a separate terminal run `python3 scripts/qwen-smoke.py`. Save the smoke measurements, then repeat success requests with the fixed benchmark prompts to compare TTFT, TPOT and throughput. Verify valid streaming, client disconnect followed by successful slot reuse, and context rejection. Report client timing with network overhead and note that SSE chunks can combine tokens.

- Record Pod scheduling, init download duration, engine startup and first readiness. Observe `kubectl -n llm-serving get pods -w` and `kubectl -n llm-serving logs deploy/qwen-serving -c snapshot`. Verify a deliberately bad checksum or path locally and confirm that no endpoint becomes ready.
- Collect memory peak from the container cgroup `memory.peak` when exposed, plus `kubectl top nodes` and `kubectl -n llm-serving top pods --containers` during cold start and generation. The bounded 512 MiB shared-memory volume is charged to workload memory. A metrics-server snapshot alone can miss peaks. Check CPU throttling and leave at least 512 MiB below the 8 GiB limit at peak.
- Review warning events and container termination states. Require zero unexpected restarts, OOMKilled, evictions or unresolved Pending Pods, `MemoryPressure=False`, all platform Applications healthy, PostgreSQL Ready and MLflow health OK. Compare Pod UIDs and restart counters with the preflight.

## Serving Node Recreation Acceptance Test

Run only with separate approval for live tests. Exercise both replacement of the underlying node while the Application remains deployed and independent removal and recreation of the serving pool. Continue to use the existing Terraform backend, plan guard and GitOps workflow above.

### Initial serving state

1. Create the serving pool with the reviewed pool-only create plan. Wait for one Ready node with the GKE pool label `cloud.google.com/gke-nodepool=serving`, custom pool label `llmops.workload=serving` and taint `llmops.workload=serving:NoSchedule`. The separate platform pool must retain its original identity and configuration.
2. Sync the reviewed Application. Run the API smoke test. Record the Application Git SHA, Deployment UID and generation, model lock revision and checksum, requested vLLM image and resolved image ID, Service UID and ClusterIP, serving node UID and Pod UID. Record all platform Pod UIDs and restart counts. Check all platform Applications are healthy, PostgreSQL is Ready and MLflow health is OK.
3. Verify the vLLM Pod is on the serving pool, and no Argo CD, MLflow or PostgreSQL Pod is there. Check every Ready serving node, including any transient surge during a managed operation. The chart requires the stable custom pool label and AMD64 via node affinity. Its toleration permits the dedicated taint. Platform workloads lack that toleration. A missing serving node leaves vLLM Pending rather than placing it on the platform pool.

These read-only commands capture placement, identity and the mounted revision. Save output privately outside Git.

```bash
kubectl get nodes -L cloud.google.com/gke-nodepool,llmops.workload,kubernetes.io/arch
kubectl get nodes -l cloud.google.com/gke-nodepool=serving -o json |
  jq '.items[] | {name:.metadata.name,uid:.metadata.uid,labels:.metadata.labels,taints:.spec.taints}'
kubectl -n argocd get application qwen-serving -o jsonpath='{.spec.source.targetRevision}{"\n"}'
kubectl -n llm-serving get deploy,svc,pods -o json |
  jq '.items[] | {kind, name:.metadata.name, uid:.metadata.uid, generation:.metadata.generation, clusterIP:.spec.clusterIP, node:.spec.nodeName, containers:.status.containerStatuses}'
kubectl -n llm-serving get configmap qwen-serving-snapshot -o json |
  python3 -c 'import base64,json,sys; lock=base64.b64decode(json.load(sys.stdin)["binaryData"]["model-lock.json"]); print(json.loads(lock)["revision"])'
kubectl -n llm-serving logs deployment/qwen-serving -c snapshot
kubectl -n argocd get applications
kubectl -n ml-platform get cluster.postgresql.cnpg.io mlflow-postgres
kubectl get --raw /api/v1/namespaces/ml-platform/services/http:mlflow:5000/proxy/health
```

### Node replacement with Application preserved

1. Use a separately approved GKE managed node replacement or observe a scheduled replacement on the serving pool only. Keep the Application, Deployment, Service and desired replica count in place. Record the replacement operation and watch the old node and Pod disappear. Leave the platform pool untouched.
2. Confirm the new node has a different UID, is Ready, and inherits the same pool labels and taint. Confirm a different vLLM Pod UID and placement on that serving node. The Deployment controller must recover its replica without a manual resync or a change to the pinned Git SHA.
3. The Pod's disk-backed `emptyDir` is lost on Pod replacement and is shared only across containers in that Pod. A container restart can reuse it. The init container on the new Pod fetches the same ~3.80 GiB snapshot and verifies every SHA-256 before the inference container starts. Record the successful init exit code and the `Verified` lines for every locked file. A missing file, hash mismatch or unavailable upstream must prevent readiness. With one replica, expect API downtime during node recovery, download and warm-up. [Kubernetes emptyDir lifecycle](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir)
4. Require the same Deployment UID and generation, Service UID and ClusterIP, Git revision, model revision and vLLM digest. Wait for Deployment availability, a ready EndpointSlice on the new Pod and successful model listing, chat completion and SSE. A port-forward attached to the old Pod may close and can be restarted locally. Record time from node loss to readiness and first successful inference.
5. During and after recovery, check PostgreSQL readiness and MLflow health. Compare platform node and Pod UIDs, readiness and restart counters. Require no unexpected platform restarts, migrations, OOM or eviction. Serving unavailability is expected within this test window.

### Full pool removal and recreation

Remove the Application and serving resources using the cleanup workflow below, then apply only the reviewed serving-pool delete plan. Confirm the pool is absent in both GKE and Terraform state while the platform and its data services remain healthy. Repeat the initial creation and GitOps sync from the same approved revision. Verify a fresh node, verified model download, readiness and API smoke test. A new Service UID or ClusterIP is expected here because the Application was intentionally removed. Record both scenarios independently.

## Rollback and cleanup

For an upgrade, locally render the last-good source and apply the Application pinned to its prior full SHA, then explicitly sync and repeat API, readiness and platform health checks. A one-replica Recreate rollback causes downtime and can fetch the verified snapshot again. For a first rollout, delete the dedicated Application after approval and wait for its cascade finalizer to finish. Verify workload and endpoint removal before the pool plan. Leave the empty serving namespace for inspection or remove it separately after inventory.

```bash
kubectl -n argocd delete application qwen-serving --wait=true --timeout=10m
kubectl -n llm-serving get deployment,service,pods,endpointslices
```

Run the approved pool-only delete plan above, then verify `serving` is absent from both GKE and state. Recheck the original pool, platform health and inventory for leftover serving disks or addresses. This operation leaves the database and its backup lifecycle intact.

The planning allowance is USD 0.18–0.20 per additional node-hour, including an allowance for disk and IPv4. A four-hour session adds roughly USD 0.72–0.80 before transfer, logs and taxes. Verify Frankfurt rates before provisioning. [Capacity and cost assumptions](../architecture/phase-5-llm-serving.md#gke-capacity-and-cost)
