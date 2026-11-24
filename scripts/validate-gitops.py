#!/usr/bin/env python3
"""Validate authored custom resources against the pinned charts' Kubernetes schemas."""

import re
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import jsonschema
import yaml


def binary_quantity_bytes(value: str) -> Decimal:
    """Parse the BinarySI subset of Kubernetes memory quantities used by this lab."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGTPE]i)", value)
    if match is None:
        raise ValueError(f"Expected a binary Kubernetes memory quantity, got {value!r}.")
    number, unit = match.groups()
    return Decimal(number) * 1024 ** ("KMGTPE".index(unit[0]) + 1)


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
            memory_limit = mlflow["resources"]["limits"].get("memory", "")
            if binary_quantity_bytes(memory_limit) != 2560 * 1024**2:
                raise ValueError(f"MLflow memory limit must equal 2560Mi, got {memory_limit}.")
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


def validate_training_job() -> None:
    image = "example.invalid/lab/training@sha256:" + "a" * 64
    renderer = "scripts/render-training-job.sh"
    job = yaml.safe_load(subprocess.check_output([renderer, image], text=True))
    if (
        job["kind"] != "Job"
        or job["metadata"] != {"generateName": "iris-training-", "namespace": "ml-platform"}
        or job["spec"]["backoffLimit"] != 0
        or job["spec"]["activeDeadlineSeconds"] <= 0
        or job["spec"]["ttlSecondsAfterFinished"] <= 0
    ):
        raise ValueError("Expected a bounded one-shot Job with a generated name.")
    pod = job["spec"]["template"]["spec"]
    training = next(container for container in pod["containers"] if container["name"] == "training")
    security = {**pod["securityContext"], **training["securityContext"]}
    if (
        training["image"] != image
        or pod.get("automountServiceAccountToken") is not False
        or pod.get("restartPolicy") != "Never"
        or pod.get("hostNetwork", False)
        or security.get("runAsNonRoot") is not True
        or min(security.get("runAsUser", 0), security.get("runAsGroup", 0)) <= 0
        or security.get("seccompProfile", {}).get("type") != "RuntimeDefault"
        or security.get("privileged", False)
        or security.get("allowPrivilegeEscalation") is not False
        or security.get("readOnlyRootFilesystem") is not True
        or security.get("capabilities") != {"drop": ["ALL"]}
        or any(volume.get("hostPath") for volume in pod.get("volumes", []))
    ):
        raise ValueError("Unexpected training image or pod security settings.")
    if subprocess.run([renderer, "example.invalid/lab/training:latest"], capture_output=True).returncode != 2:
        raise ValueError("The training renderer must reject a mutable image tag.")
    print("Validated one-shot training Job, image digest and security settings")


def tolerates_serving_taint(toleration: dict) -> bool:
    if toleration.get("effect") not in (None, "", "NoSchedule"):
        return False
    if toleration.get("operator") == "Exists":
        return toleration.get("key") in (None, "", "llmops.workload")
    return toleration.get("key") == "llmops.workload" and toleration.get("value") == "serving"


def validate_serving_deployment(deployment: dict) -> None:
    spec = deployment["spec"]
    pod = spec["template"]["spec"]
    if spec.get("replicas", 1) > 1 or spec["strategy"]["type"] != "Recreate":
        raise ValueError("Serving requires at most one replica and Recreate")
    if "nodeName" in pod or any(pod.get(field) for field in ("hostNetwork", "hostPID", "hostIPC")):
        raise ValueError("Serving must use pool placement without fixed node or host namespaces")
    affinity = pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    required = [
        {"key": "llmops.workload", "operator": "In", "values": ["serving"]},
        {"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]},
    ]
    terms = affinity["nodeSelectorTerms"]
    if not terms or any(not all(item in term.get("matchExpressions", []) for item in required) for term in terms):
        raise ValueError("Every serving affinity term must require the pool label and AMD64")
    toleration = {"key": "llmops.workload", "operator": "Equal", "value": "serving", "effect": "NoSchedule"}
    if pod.get("tolerations") != [toleration]:
        raise ValueError("Serving must use only the dedicated NoSchedule toleration")

    name = deployment["metadata"]["name"]
    if pod.get("automountServiceAccountToken") is not False or pod.get("serviceAccountName") != name:
        raise ValueError("Serving must use its own ServiceAccount with token automount disabled")
    identity = {
        "runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001, "fsGroup": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    if pod.get("securityContext") != identity:
        raise ValueError("Serving requires its non-root UID/GID and RuntimeDefault seccomp")
    if ([container["name"] for container in pod["containers"]] != ["vllm"]
            or [container["name"] for container in pod.get("initContainers", [])] != ["snapshot"]
            or pod.get("ephemeralContainers")):
        raise ValueError("Expected only the snapshot init and vLLM containers")
    serving, init = pod["containers"][0], pod["initContainers"][0]
    if serving.get("command") or serving.get("args", [])[:1] != ["/models/qwen3"]:
        raise ValueError("vLLM must serve the verified local model")
    if [env for env in serving.get("env", []) if env["name"] == "HF_HUB_OFFLINE"] != [
        {"name": "HF_HUB_OFFLINE", "value": "1"},
    ]:
        raise ValueError("vLLM must load the snapshot offline")
    annotations = spec["template"]["metadata"].get("annotations", {})
    if not re.fullmatch(r"[a-f0-9]{64}", annotations.get("checksum/snapshot", "")):
        raise ValueError("Serving rollout must track the snapshot ConfigMap checksum")
    security = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    for container in (serving, init):
        if not re.fullmatch(r"[a-z0-9./:_-]+@sha256:[a-f0-9]{64}", container["image"]):
            raise ValueError("Serving images must be digest-pinned")
        if container.get("securityContext") != security:
            raise ValueError("Serving requires restricted container securityContext")

    budgets = (
        (serving, ("2500m", "6Gi", "6Gi"), ("3500m", "8Gi", "14Gi")),
        (init, ("500m", "256Mi", "6Gi"), ("1", "1Gi", "14Gi")),
    )
    keys = ("cpu", "memory", "ephemeral-storage")
    for container, requests, limits in budgets:
        expected = {"requests": dict(zip(keys, requests)), "limits": dict(zip(keys, limits))}
        if container.get("resources") != expected:
            raise ValueError(f"Unexpected serving resource budget: {container['name']}")

    for probe, timing in (("startupProbe", (10, 3, 60)), ("readinessProbe", (5, 3, 3)), ("livenessProbe", (15, 5, 4))):
        expected = dict(zip(("periodSeconds", "timeoutSeconds", "failureThreshold"), timing))
        expected["httpGet"] = {"path": "/health", "port": "http"}
        if serving.get(probe) != expected:
            raise ValueError(f"Unexpected serving probe: {probe}")
    if init.get("command") != ["timeout", "900", "python", "-B", "/snapshot/model_snapshot.py"] or init.get("args") != [
        "/snapshot/model-lock.json", "/models/qwen3",
    ]:
        raise ValueError("Serving must run the bounded verified snapshot init")

    volumes = {
        "snapshot": {"configMap": {"name": f"{name}-snapshot"}},
        "models": {"emptyDir": {"sizeLimit": "12Gi"}},
        "temp": {"emptyDir": {"sizeLimit": "1Gi"}},
        "shm": {"emptyDir": {"medium": "Memory", "sizeLimit": "512Mi"}},
    }
    rendered_volumes = pod.get("volumes", [])
    by_name = {volume["name"]: {key: value for key, value in volume.items() if key != "name"}
               for volume in rendered_volumes}
    if len(rendered_volumes) != len(volumes) or by_name != volumes:
        raise ValueError("Unexpected serving volumes")
    mounts = (
        (serving, [
            {"name": "models", "mountPath": "/models", "readOnly": True},
            {"name": "temp", "mountPath": "/tmp"},
            {"name": "shm", "mountPath": "/dev/shm"},
        ]),
        (init, [
            {"name": "snapshot", "mountPath": "/snapshot", "readOnly": True},
            {"name": "models", "mountPath": "/models"},
        ]),
    )
    for container, expected in mounts:
        if sorted(container.get("volumeMounts", []), key=lambda mount: mount["name"]) != sorted(
            expected, key=lambda mount: mount["name"]
        ) or container.get("volumeDevices"):
            raise ValueError(f"Unexpected serving volume mounts: {container['name']}")


def validate_serving_placement(resources: list[dict]) -> None:
    serving = None
    for resource in resources:
        if resource["kind"] not in ("Deployment", "StatefulSet"):
            continue
        pod = resource["spec"]["template"]["spec"]
        if resource["metadata"]["name"] == "qwen-serving":
            serving = resource
        elif any(map(tolerates_serving_taint, pod.get("tolerations", []))):
            raise ValueError(f"Platform workload tolerates the serving taint: {resource['metadata']['name']}")

    for path in ("gitops/apps/mlflow/deployment.yaml", "gitops/apps/cloudnative-pg/cluster.yaml"):
        resource = yaml.safe_load(Path(path).read_text())
        spec = resource["spec"]
        pod = spec["template"]["spec"] if resource["kind"] == "Deployment" else spec.get("affinity", {})
        if any(map(tolerates_serving_taint, pod.get("tolerations", []))):
            raise ValueError(f"Data workload tolerates the serving taint: {path}")

    if serving is None:
        raise ValueError("Serving Deployment is missing")
    validate_serving_deployment(serving)
    services = [item for item in resources if item["kind"] == "Service"
                and item["metadata"]["name"] == "qwen-serving"]
    if len(services) != 1 or services[0]["spec"].get("type", "ClusterIP") != "ClusterIP":
        raise ValueError("Serving requires one private ClusterIP Service")
    print("Validated serving pool placement and platform taint isolation")


def main() -> None:
    schemas = {}
    workloads = []
    for filename in sys.argv[1:]:
        with Path(filename).open() as stream:
            for resource in yaml.safe_load_all(stream):
                if not resource:
                    continue
                if resource["kind"] != "CustomResourceDefinition":
                    workloads.append(resource)
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
    validate_training_job()
    validate_serving_placement(workloads)


if __name__ == "__main__":
    main()
