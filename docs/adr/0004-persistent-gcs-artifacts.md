# 0004. GCS for persistent model artifacts

Use a regional Standard GCS bucket separate from the Terraform state bucket for stable artifact URIs. Eventually organize datasets, MLflow artifacts, checkpoints and evaluation results by prefix. PostgreSQL stores experiment and registry metadata. GCS stores experiment outputs and model files. Recovering one store requires independently preserving its related data in the other.

Block public access and use uniform bucket-level access. Add a narrow workload principal and IAM binding in Phase 3 after approval. Revisit separate buckets when services need different authorization or retention boundaries. Start with no artifact expiry automation so evaluation and registry references remain valid. Review soft-delete storage and version retention costs before loading large models.
