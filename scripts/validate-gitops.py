#!/usr/bin/env python3
"""Validate authored custom resources against the pinned charts' Kubernetes schemas."""

import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

import jsonschema
import yaml


def validate_mlflow_overrides() -> None:
    """Exercise the replica and image overrides that Argo passes to Kustomize."""
    manifests = Path("gitops/apps/mlflow")
    application = yaml.safe_load(Path("gitops/applications/mlflow.yaml").read_text())
    source = application["spec"]["source"]["kustomize"]
    image_name, placeholder = source["images"][0].split("=")
    if placeholder != "@MLFLOW_IMAGE@" or source["replicas"] != [{"name": "mlflow", "count": 1}]:
        raise ValueError("Unexpected MLflow image or replica override in the Application.")
    registry_image = "example.invalid/lab/mlflow"
    digest = "sha256:" + "a" * 64
    for replicas in (0, 1):
        with TemporaryDirectory() as directory:
            overlay = Path(directory) / "mlflow"
            shutil.copytree(manifests, overlay)
            path = overlay / "kustomization.yaml"
            config = yaml.safe_load(path.read_text())
            config["replicas"] = [{"name": "mlflow", "count": replicas}]
            config["images"] = [{"name": image_name, "newName": registry_image, "digest": digest}]
            path.write_text(yaml.safe_dump(config))
            output = subprocess.check_output(["kubectl", "kustomize", str(overlay)], text=True)
            deployment = next(doc for doc in yaml.safe_load_all(output) if doc["kind"] == "Deployment")
            spec = deployment["spec"]
            pod = spec["template"]["spec"]
            mlflow = next(container for container in pod["containers"] if container["name"] == "mlflow")
            image = mlflow["image"]
            if spec["replicas"] != replicas or image != f"{registry_image}@{digest}":
                raise ValueError("MLflow replica or digest override did not affect the Deployment.")
            if mlflow["resources"]["limits"].get("memory") != "2Gi":
                raise ValueError("MLflow must retain its explicit 2Gi memory limit.")
            for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
                probe = mlflow[probe_name]
                http = probe["httpGet"]
                if (
                    probe.get("timeoutSeconds") != 5
                    or http.get("path") != "/health"
                    or http.get("port") != "http"
                    or {"name": "Host", "value": "localhost"} not in http.get("httpHeaders", [])
                ):
                    raise ValueError(f"Unexpected MLflow HTTP settings for {probe_name}.")
            security = {**pod["securityContext"], **mlflow["securityContext"]}
            if (
                pod.get("serviceAccountName") != "mlflow"
                or pod.get("automountServiceAccountToken") is not False
                or security.get("runAsNonRoot") is not True
                or min(security.get("runAsUser", 0), security.get("runAsGroup", 0)) <= 0
                or security.get("seccompProfile", {}).get("type") != "RuntimeDefault"
                or security.get("allowPrivilegeEscalation") is not False
                or security.get("readOnlyRootFilesystem") is not True
                or security.get("privileged", False) is not False
                or security.get("capabilities") != {"drop": ["ALL"]}
            ):
                raise ValueError("MLflow security settings have been weakened.")
    print("Validated MLflow digest, replica overrides, resources, probes and security settings")


def main() -> None:
    schemas = {}
    for filename in sys.argv[1:]:
        with Path(filename).open() as stream:
            for resource in yaml.safe_load_all(stream):
                if not resource or resource["kind"] != "CustomResourceDefinition":
                    continue
                spec = resource["spec"]
                for version in spec["versions"]:
                    if version["served"]:
                        key = (f"{spec['group']}/{version['name']}", spec["names"]["kind"])
                        schemas[key] = version["schema"]["openAPIV3Schema"]

    manifests = sorted(Path("gitops/applications").glob("*.yaml"))
    manifests.append(Path("gitops/apps/cloudnative-pg/cluster.yaml"))
    for manifest in manifests:
        resource = yaml.safe_load(manifest.read_text())
        schema = schemas[(resource["apiVersion"], resource["kind"])]
        jsonschema.Draft7Validator(schema).validate(resource)
        print(f"Validated {manifest}")

    validate_mlflow_overrides()


if __name__ == "__main__":
    main()
