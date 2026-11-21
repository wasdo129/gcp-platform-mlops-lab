# 0003. CloudNativePG with an operator-held backup

Use one CNPG-managed PostgreSQL primary with dynamic CSI storage. Keep a custom-format logical dump on the Mac, validate it before publication and require a fresh verified archive before normal teardown. Restore as the application owner over a local peer-authenticated PostgreSQL connection within a single transaction into a fresh database.

A local backup has no continuous WAL or point-in-time recovery. A disk may survive GKE deletion and incur charges. Treat retained disks as cleanup or recovery candidates after verification and review. The database connection limit gates ordinary clients during restore and teardown. Administrative sessions must be coordinated separately.
