# 0001. Ephemeral zonal GKE Standard

Use GKE Standard in one zone and a fixed single CPU node so the operator can study scheduling and later add explicitly approved GPU pools. Trade away zonal resilience for lower idle cost and session-based lifecycle. Use an isolated custom VPC, VPC-native addressing, Dataplane V2 and a DNS-only control plane.

Private node networking is the Terraform default. For the initial public-source GitOps exercise, approve one ephemeral external node IP to reach GitHub, chart repositories and public image registries. Revisit private egress before adding workloads or tenants. An on-demand NAT adds routing, billing and cleanup. Sharing the existing default VPC inherits broader ingress and requires subnet changes.
