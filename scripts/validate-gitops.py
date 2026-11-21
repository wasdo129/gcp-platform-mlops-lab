#!/usr/bin/env python3
"""Validate authored custom resources against the pinned charts' Kubernetes schemas."""

import sys
from pathlib import Path

import jsonschema
import yaml


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


if __name__ == "__main__":
    main()
