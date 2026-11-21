# LLMOps platform roadmap

| Phase | Scope | Evidence required |
| --- | --- | --- |
| 1. Cloud foundation | Two Terraform states, zonal CPU GKE Standard, dedicated node identity, Workload Identity Federation, isolated VPC | Reviewed apply, DNS API access, CPU workload scheduled, foundation survives lab removal |
| 2. GitOps and database | Argo CD, CloudNativePG, local logical backup and guarded teardown | Seed a row, back up, destroy, recreate, restore the exact archive and query the row |
| 3. MLflow | Tracking and registry metadata in PostgreSQL, proxied GCS artifact access using a dedicated KSA | Persist a run, model version and artifact across cluster recreation |
| 4. Argo Workflows | Prepare datasets, evaluate, log to MLflow and publish outputs to GCS | Demonstrate retries, failed-step visibility and durable outputs |
| 5. LLM serving | Qwen3-1.7B, tokenizer, memory and KV cache, Transformers baseline, Helm-packaged vLLM | Test model listing, completion, streaming, readiness and startup failure |
| 6. GPU performance | GKE-managed drivers and plugin, dedicated tainted pool, DCGM, vLLM Bench, quantization | Confirm trial eligibility and quota first. Measure TTFT, TPOT, throughput, utilization and cost per million tokens |
| 7. Fine-tuning | Transformers, PEFT, TRL, QLoRA, reproducible splits and checkpoints | Compare baseline and adapter on a held-out dataset. Reject failing models |
| 8. Delivery and promotion | GitHub Actions, WIF, Artifact Registry, immutable images, GitOps canary and rollback | Promote only evaluated models and demonstrate rollback |
| 9. Reliability | Prometheus, Grafana, OpenTelemetry, SLOs, alerts and controlled failure injection | Link alerts to measurable failures and test recovery playbooks |
| 10. Architecture and interviews | Standard vs Autopilot vs kubeadm, KServe vs vLLM/Ray Serve, parallelism, MIG, tenancy and capacity | Produce sizing estimates, architecture diagrams, ADRs and troubleshooting scenarios |

Phases 1 and 2 have repository implementations. Their GKE acceptance test is pending explicit deployment approval. See the [integration runbook](runbooks/integration.md).
