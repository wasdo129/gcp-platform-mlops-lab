# Phase 5 proposal: Qwen3 CPU serving

## Recommendation

After approval, benchmark Qwen3-1.7B with Transformers on a local CPU. Then run one CPU-only vLLM replica on a temporary, dedicated zonal `e2-standard-4` node pool in `europe-west3-a`. Keep the existing platform pool and its workloads in place. BF16 on the target host is a deployment gate. Verify the actual CPU flags, runtime compatibility and memory peak before accepting the configuration. If BF16 is incompatible or too slow, stop and present the measured FP32 or quantized alternatives for review. GPU serving is Phase 6.

## Model and runtime compatibility

Use the public Apache-2.0 `Qwen/Qwen3-1.7B` snapshot at `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`. Pin the tokenizer, chat template and weights together. The model card documents Transformers 4.51.0 as the Qwen3 compatibility floor. Use a Python 3.12 environment with exact, tested native CPU PyTorch and Transformers pins selected during implementation. For vLLM, start qualification with release 0.34.0 and its Linux CPU wheel or image. Keep its dependency lock separate from the Transformers baseline. Pin the verified image by digest. Documentation compatibility is established. CPU binaries, warm-up and inference have yet to be tested. [Qwen3 model card](https://huggingface.co/Qwen/Qwen3-1.7B) · [Transformers Qwen3](https://huggingface.co/docs/transformers/en/model_doc/qwen3) · [vLLM release](https://github.com/vllm-project/vllm/releases/tag/v0.34.0)

| Runtime | Use in Phase 5 | CPU and trade-offs |
| --- | --- | --- |
| Transformers + PyTorch | Local FP32 reference, then optional BF16 comparison | Native macOS arm64 or Linux amd64/arm64 with supported CPU PyTorch wheels. Simple single-process generation and memory measurement. Benchmark on native CPU to avoid emulation distortion. |
| vLLM CPU | GKE serving and streaming | Linux amd64 with AVX2 for limited support or AVX-512F preferred. Linux AArch64 requires NEON. BF16 acceleration depends on host ISA and build, including AVX-512 BF16 or AMX BF16 on relevant x86 hosts and Arm BF16 extensions on supporting Arm hosts. Check actual flags and startup. macOS arm64 CPU support is experimental and source-built. |
| llama.cpp + GGUF | Optional quantized CPU reference if needed | Separate engine with efficient CPU inference and an OpenAI-compatible server. Qwen publishes Q8_0. A Q4 variant would require pinned, verified provenance and quality testing. |

vLLM provides the OpenAI-compatible server, paged KV cache and continuous batching. The first profile uses one sequence, so compare latency and memory without assuming a batching throughput benefit. Check the image on the actual node with `lscpu` or `/proc/cpuinfo` and record `avx2`, `avx512f` and BF16 flags where present. E2 machine names give a capacity target. They do not qualify the binary or BF16 kernels. [vLLM CPU installation](https://docs.vllm.ai/en/v0.34.0/getting_started/installation/cpu/) · [Qwen deployment guide](https://qwen.readthedocs.io/en/latest/deployment/vllm.html) · [Google machine families](https://docs.cloud.google.com/compute/docs/general-purpose-machines)

## Transformers baseline

After download approval, create the pinned snapshot outside Git. Use `AutoTokenizer` and `AutoModelForCausalLM` with explicit CPU placement, FP32, safetensors, `local_files_only=True` and `trust_remote_code=False`. Set PyTorch intra-op threads to 2 initially and inter-op threads to 1. Use `eval()`, `torch.inference_mode()`, SDPA where supported and eager attention as a diagnostic fallback. Render chat with `apply_chat_template`, `add_generation_prompt=True` and `enable_thinking=False`. Use greedy decoding, batch 1, a 2048-token total budget including the chat template, and at most 128 generated tokens. Keep prompts and settings identical across comparison runs.

Record model file size, startup time, warm and cold first-token latency, output tokens per second, peak RSS and logical CPU count. Compare BF16 correctness and performance only if the local build supports it. Use a machine with at least 16 GiB physical RAM and verify at least 10 GiB of available memory before the FP32 load. Record host and container or process memory limits. [Transformers Qwen3](https://huggingface.co/docs/transformers/en/model_doc/qwen3)

## Memory and storage estimates

Approximate weight memory uses 1.7 billion parameters times bytes per weight. The pinned upstream BF16 snapshot occupies about 4.08 GB decimal including config and tokenizer. Its two safetensors shards total about 4.06 GB decimal. Disk size and RSS should be measured separately because of file mappings, cast buffers, kernel packing and allocator overhead.

| Format | Raw weight estimate | Practical implication |
| --- | ---: | --- |
| FP32 | 6.33 GiB | Local reference. Allow roughly 8–10 GiB total with runtime and startup overhead. The serving profile below is sized for BF16. |
| BF16 | 3.17 GiB | Proposed vLLM dtype. Budget up to 3.8 GiB for weights as a conservative first estimate, 1–2 GiB for runtime and workspaces, 0.5 GiB for KV and up to 1.5 GiB startup contingency. Validate the 8 GiB limit from cgroup measurements. |
| INT8 / GGUF Q8_0 | 1.58 GiB ideal | The upstream Q8_0 file is 1.83 GB decimal, about 1.70 GiB. Use llama.cpp for this path. vLLM compressed-tensors W8A8 uses a different checkpoint and requires a supported CPU kernel. |
| INT4 / AWQ or GPTQ / GGUF Q4 | 0.79 GiB ideal | Approximate 1.0–1.3 GiB for a candidate with scales and mixed tensor types, subject to actual checkpoint size. CPU AWQ/GPTQ support is version and ISA dependent. Validate exact format, provenance, quality and latency before use. |

Quantized weights leave the KV cache dtype unchanged unless separately configured and supported. Qwen3 has 28 layers, 8 KV heads and head dimension 128. KV cache per token per sequence is `2 × 28 × 8 × 128 × dtype_bytes`, or 112 KiB BF16 and 224 KiB FP32. At 2048 total tokens that is 224 MiB BF16 or 448 MiB FP32 for one sequence. At two sequences, double those figures. At the native 32768-token context it is 3.5 GiB BF16 per sequence. The first profile caps model length at 2048, allows one sequence, and explicitly budgets 512 MiB for BF16 KV via `--kv-cache-memory-bytes 536870912` after confirming the flag on the pinned CPU build. Cache rounding, activation buffers and the server are additional. [Pinned files](https://huggingface.co/Qwen/Qwen3-1.7B/tree/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e) · [Pinned model config](https://huggingface.co/Qwen/Qwen3-1.7B/blob/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e/config.json) · [Qwen GGUF](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/tree/main) · [vLLM quantization](https://docs.vllm.ai/en/latest/features/quantization/)

### Model loading

Use a bounded disk-backed `emptyDir` for the first lab. A pinned init image downloads only the required tokenizer, config, license, index and safetensors files from the exact Hugging Face revision. Verify file SHA-256 against an independently reviewed manifest and mark the snapshot complete only after all files pass. Serve from that path with a read-only mount and offline loader settings. The public snapshot needs no Hub credential. Set explicit download timeouts and bounded retries per init attempt. Kubernetes may retry failed init attempts, so bound the operator's rollout wait and stop reconciliation through the reviewed rollback path on failure. A restarted serving container reuses the Pod volume. A recreated Pod downloads again. Allow at least 12 GiB for the model cache and temporary download files, plus writable scratch and image layers on the node. Validate node filesystem capacity and cold download time. Keep weights out of Git and the runtime image. A dedicated PVC or read-only versioned mirror can be reviewed if repeated downloads dominate startup. The MLflow artifact and Terraform state buckets are outside the model path. [Hugging Face download and revision pinning](https://huggingface.co/docs/huggingface_hub/en/guides/download)

## GKE capacity and cost

The 24 November 2026 read-only snapshot showed one Ready `e2-standard-2`, five Synced and Healthy Applications, 1675m CPU requests and 4619 MiB node memory usage, including 1888 MiB MLflow. Allocatable is 1930m and approximately 6026 MiB. Headroom was 255m and approximately 1407 MiB before allowing for MLflow growth up to 2560 MiB. Even BF16 weight memory alone exceeds that snapshot's headroom. Scheduling uses requests per node. Separate small nodes cannot pool RAM or CPU for this single Pod.

| Approach | Capacity and risk | Approximate additional cost |
| --- | --- | --- |
| Local CPU only | Good for baseline and fast iteration. GKE scheduling, probes and client path remain untested. | USD 0 in GCP |
| Add a second `e2-standard-2` | At most 2 vCPU, 8 GiB nominal. Too small for the proposed serving Pod after GKE reservations and system workloads. Could qualify a separate quantized profile with smaller requests. | Roughly USD 0.09–0.11/h with boot disk and optional IPv4 |
| Replace platform node with `e2-standard-4` | Roughly 3920m allocatable as a planning estimate. Existing 1675m plus serving 2500m exceeds it by about 255m. Also couples serving pressure and node migration to CNPG and MLflow. A larger replacement could fit but still requires a migration plan. | About USD 0.08–0.10/h more compute for standard-4 vs standard-2 after migration |
| Add one dedicated `e2-standard-4` temporarily | 4 vCPU, 16 GiB nominal. With 3920m estimated allocatable and 740m conservative system requests, a 2500m serving Pod leaves about 680m. Verify real system requests and free RAM before rollout. Existing platform pool remains in service. | Budget USD 0.18–0.20/h extra, about USD 0.72–0.80 per four-hour session |

These are planning allowances for Frankfurt on-demand Linux capacity, rounded from roughly USD 0.086/h and USD 0.173/h for the two E2 VM sizes. Recheck the regional quote before provisioning. Allow about USD 0.005/h for a 30 GiB balanced boot disk and USD 0.005/h for an external IPv4 if used. Existing zonal GKE management charges continue once per cluster. The additional pool adds no second cluster fee. Storage, network transfers, logs and taxes can change the invoice. At 730 hours, the dedicated node allowance is about USD 131–146 extra. Shut down the temporary capacity after the approved experiment. [Compute pricing](https://cloud.google.com/products/compute/pricing/general-purpose) · [Disk pricing](https://cloud.google.com/compute/disks-image-pricing) · [External IPv4 pricing](https://cloud.google.com/vpc/network-pricing) · [GKE pricing](https://cloud.google.com/kubernetes-engine/pricing)

## Kubernetes design

Reuse the lab ownership model. Terraform may define an optional serving pool in the existing GKE root after approval. Use a pool label and taint with a specific selector and toleration for the serving Pod. Argo CD owns the Helm-rendered resources from a pinned, reachable Git SHA. Start with namespace `llm-serving`, one Deployment replica and a ClusterIP Service on port 8000. Use `Recreate` to avoid scheduling two model replicas during updates. Short downtime is acceptable for this lab.

| Container | CPU request / limit | Memory request / limit | Ephemeral storage request / limit |
| --- | --- | --- | --- |
| Model download init | 500m / 1000m | 256Mi / 1Gi | 6Gi / 14Gi |
| vLLM | 2500m / 3500m | 6Gi / 8Gi | 6Gi / 14Gi |

Kubernetes uses the maximum of the regular init and steady-state requests for each resource. The shared volume counts toward Pod ephemeral storage. Set the disk-backed model cache size limit to 12 GiB and provision separate bounded writable scratch. Verify live allocatable and node image filesystem capacity. Before acceptance require at least 2500m schedulable CPU and 9 GiB of observed free allocatable memory on the dedicated node before serving starts. Reserve 1 GiB beyond the Pod's 8 GiB limit for variability. Begin with two worker threads and verify effective CPU affinity/quota and throttling. Cap client-side concurrency at one and validate overload behavior separately. [GKE node sizing](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/plan-node-sizes)

Proposed chart files under `gitops/charts/qwen-serving/` are `Chart.yaml`, `values.yaml`, `values.schema.json`, and templates for Deployment, Service and ServiceAccount. Add an Application under `gitops/applications/` with a separate opt-in deployment path. Values carry digest, model revision, file hashes, dtype, context cap, resources, volumes, and pool placement. Render and validate the probe and security settings in CI. A policy resource may restrict access when the cluster's policy support is verified.

- Startup probe uses HTTP `/health`, initially every 10 s with a 3 s timeout and 60 failures. It covers engine startup and warm-up after init completes. Monitor and time-bound downloads separately because the startup probe starts after init.
- Readiness uses HTTP `/health` every 5 s with a 3 s timeout and 3 failures. Check after cold start that the endpoint stays unavailable until the engine can serve. Exercise a real generation in acceptance.
- Liveness uses HTTP `/health` every 15 s with a 5 s timeout and 4 failures, after startup succeeds. Validate that CPU saturation does not cause spurious restarts. Probes make no token-generation requests. [Kubernetes probes](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes)
- Apply non-root UID/GID 10001, `allowPrivilegeEscalation: false`, dropped capabilities, `RuntimeDefault` seccomp, read-only root filesystem, explicit writable scratch and disabled ServiceAccount token automount. Test the CPU backend with these settings. A build requiring host access or relaxed seccomp needs separate review.
- Use a private ClusterIP and operator loopback port-forward. Verify `GET /v1/models`, `POST /v1/chat/completions` and SSE using `stream: true`. Expose model alias `qwen3-1.7b`. Set `chat_template_kwargs.enable_thinking=false` and `max_tokens=128` in the acceptance client. Apply the 2048-token total context limit on the server. A ClusterIP is reachable from other cluster workloads, so review ingress restrictions before using sensitive prompts. Keep prompts and credentials out of logs. Public access is outside this lab scope. [vLLM OpenAI-compatible API](https://docs.vllm.ai/en/v0.34.0/serving/online_serving/openai_compatible_server/) · [Qwen vLLM deployment guide](https://qwen.readthedocs.io/en/latest/deployment/vllm.html)

Candidate serving command for image qualification:

```bash
vllm serve /models/qwen3 --host 0.0.0.0 --port 8000 \
  --served-model-name qwen3-1.7b --dtype bfloat16 --max-model-len 2048 \
  --max-num-seqs 1 --kv-cache-memory-bytes 536870912
```

Use the CPU image or wheel to select the backend. Verify these CLI flags and the selected device in startup logs during image qualification.

## Implementation and acceptance

1. After review and model-download approval, pin and verify the snapshot and CPU dependencies. Capture the local Transformers FP32 baseline, with BF16 measured separately when available.
2. Qualify the pinned vLLM CPU build and the same checkpoint, including the restrictive security context, dtype, KV budget and output format. Prepare the chart, GitOps Application, smoke test and runbook. Run Helm lint/template, Kubernetes schema and GitOps checks. Score results against the same small set of prompts and token limits as the local baseline.
3. After infrastructure approval, review the Terraform plan for the temporary pool. Require no replacement of the existing cluster or platform pool. Check placement, ISA, CPU flags, allocatable and observed headroom on the new node. Obtain rollout approval before syncing the Application.
4. Accept successful cold startup within the configured budget, healthy readiness, a stable model alias, nonempty bounded completion, multiple valid SSE chunks and terminal completion, plus successful recovery after client cancellation. Confirm oversized context is rejected. Run 10 sequential completions and record TTFT, TPOT, tokens/s, cold-start time, cgroup memory peak and CPU throttling. Use the baseline to agree a latency target before live rollout. Reserve at least 512 MiB below the 8 GiB limit at the observed cold-start and serving peak. Require zero serving restarts or OOM, no MemoryPressure or unexpected Pending Pods, and unchanged MLflow/PostgreSQL UIDs, readiness and restart counters.
5. Test failure using a deliberately invalid model path or checksum in an isolated local release. Require a bounded startup failure, clear events/logs and no ready endpoint. Exercise rollback in the local release and verify the previous revision responds. Compare steady and cold-start measurements before considering higher context or concurrency.

## Rollback

Point Argo CD back to the previous approved Git SHA, which also fixes the last-good image digest and model revision. Let the single replica recreate, then verify readiness and the API smoke test. For a first rollout with no prior serving release, use the reviewed Git revision with serving disabled. If disabling the Application, verify its managed resources and endpoints are gone before any separately approved node-pool teardown. Recheck platform health and inventory residual disks or addresses. Preserve PostgreSQL, MLflow metadata and artifacts. A one-replica rollback has a serving interruption and may download the model again.
