# LLMOps platform roadmap

| Phase | Scope | Evidence required |
| --- | --- | --- |
| 1. Cloud foundation | Two Terraform states, zonal CPU GKE Standard, dedicated node identity, Workload Identity Federation, isolated VPC | Reviewed apply, DNS API access, CPU workload scheduled, foundation survives lab removal |
| 2. GitOps and database | Argo CD, CloudNativePG, local logical backup and guarded teardown | Seed a row, back up, destroy, recreate, restore the exact archive and query the row |
| 3. MLflow | Tracking and registry metadata in PostgreSQL, proxied GCS artifact access using a dedicated KSA | Write and read a run and artifact through the SDK, with direct PostgreSQL and GCS evidence |
| 4. CPU training | On-demand Iris training Job with immutable image and MLflow tracking | Complete the Job on GKE and verify the run, metrics and saved model through MLflow |
| 5. LLM serving | Qwen3-1.7B, tokenizer, memory and KV cache, Transformers CPU baseline and isolated Helm-packaged vLLM CPU serving | Test model listing, completion, streaming, readiness and startup failure |
| 6. GPU performance | GKE-managed drivers and plugin, dedicated tainted pool, DCGM, vLLM Bench, quantization | Confirm trial eligibility and quota first. Measure TTFT, TPOT, throughput, utilization and cost per million tokens |
| 7. Fine-tuning | Transformers, PEFT, TRL, QLoRA, reproducible splits and checkpoints | Compare baseline and adapter on a held-out dataset. Reject failing models |
| 8. Delivery and promotion | GitHub Actions, WIF, Artifact Registry, immutable images, GitOps canary and rollback | Promote only evaluated models and demonstrate rollback |
| 9. Reliability | Prometheus, Grafana, OpenTelemetry, SLOs, alerts and controlled failure injection | Link alerts to measurable failures and test recovery playbooks |
| 10. Architecture and interviews | Standard vs Autopilot vs kubeadm, KServe vs vLLM/Ray Serve, parallelism, MIG, tenancy and capacity | Produce sizing estimates, architecture diagrams, ADRs and troubleshooting scenarios |

Phases 1 and 2 passed live acceptance. The GKE recreation test passed with PostgreSQL data restored from backup. See the [integration runbook](runbooks/integration.md).

Phase 3 passed live MLflow acceptance with SDK tracking, independent PostgreSQL and GCS verification, and healthy Argo CD reconciliation. See the [MLflow runbook](runbooks/mlflow.md).

Phase 4 passed GKE end-to-end acceptance on 24 November 2026. See the [training runbook and acceptance record](runbooks/training.md#phase-4-acceptance-record).

Phase 5 is in architecture review. See the [Qwen3 CPU serving proposal](architecture/phase-5-llm-serving.md). GPU serving and performance work remain in Phase 6.
