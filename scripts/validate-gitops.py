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
            image = spec["template"]["spec"]["containers"][0]["image"]
            if spec["replicas"] != replicas or image != f"{registry_image}@{digest}":
                raise ValueError("MLflow replica or digest override did not affect the Deployment.")
    print("Validated MLflow Kustomize overrides for start and teardown")


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
