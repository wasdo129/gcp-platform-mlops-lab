# 0002. Terraform and Argo CD ownership

Terraform manages GCP resources in independent foundation and lab states. Helm installs Argo CD and its CRDs with chart versions pinned. GitOps manages Argo CD configuration, CNPG and CPU workloads. Bootstrap enforces dependency readiness before creating the database Application.

Pin Git sources to a published commit. Update the commit deliberately to promote changes. Keep automated pruning disabled during these phases to protect stateful objects from accidental Git deletions. Use no Terraform Helm provider. Future database consumers must start after the database initialization gate.
