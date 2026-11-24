import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("validate_gitops", ROOT / "scripts/validate-gitops.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
IDENTITY = {"project": "lab", "location": "zone", "cluster": "cluster", "name": "serving"}
POOL = "google_container_node_pool.serving[0]"


class ServingDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.check_output([
            "helm", "template", "qwen-serving", "gitops/charts/qwen-serving", "-n", "llm-serving",
        ], cwd=ROOT, text=True)
        cls.deployment = next(item for item in yaml.safe_load_all(rendered) if item["kind"] == "Deployment")

    def test_chart_profile(self):
        VALIDATOR.validate_serving_deployment(self.deployment)

    def test_rejects_unsafe_or_unqualified_profile(self):
        changes = (
            (("replicas",), 2, "one replica"),
            (("strategy", "type"), "RollingUpdate", "Recreate"),
            (("template", "spec", "nodeName"), "platform-node", "fixed node"),
            (("template", "spec", "automountServiceAccountToken"), True, "token automount"),
            (("template", "spec", "securityContext", "runAsUser"), 0, "non-root"),
            (("template", "spec", "securityContext", "seccompProfile", "type"), "Unconfined", "seccomp"),
            (("template", "spec", "tolerations"), [{"operator": "Exists"}], "dedicated"),
            (("template", "spec", "initContainers", 0, "image"), "python:latest", "digest-pinned"),
            (("template", "spec", "containers", 0, "securityContext", "capabilities", "add"), ["SYS_ADMIN"], "restricted"),
            (("template", "spec", "containers", 0, "securityContext", "privileged"), True, "restricted"),
            (("template", "spec", "containers", 0, "securityContext", "readOnlyRootFilesystem"), False, "restricted"),
            (("template", "spec", "containers", 0, "resources", "limits", "ephemeral-storage"), "1Gi", "resource budget"),
            (("template", "spec", "containers", 0, "readinessProbe", "httpGet", "path"), "/", "readinessProbe"),
            (("template", "spec", "containers", 0, "volumeMounts", 0, "readOnly"), False, "volume mounts"),
            (("template", "spec", "volumes", 2, "hostPath"), {"path": "/"}, "volumes"),
        )
        for path, value, reason in changes:
            with self.subTest(path=path):
                deployment = copy.deepcopy(self.deployment)
                field = deployment["spec"]
                for part in path[:-1]:
                    field = field[part]
                field[path[-1]] = value
                with self.assertRaisesRegex(ValueError, reason):
                    VALIDATOR.validate_serving_deployment(deployment)

    def test_every_or_term_must_require_pool_and_amd64(self):
        deployment = copy.deepcopy(self.deployment)
        pod = deployment["spec"]["template"]["spec"]
        terms = pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
        terms.append({"matchExpressions": terms[0]["matchExpressions"][:1]})
        with self.assertRaisesRegex(ValueError, "pool label and AMD64"):
            VALIDATOR.validate_serving_deployment(deployment)


class ServingPlanTests(unittest.TestCase):
    def accepted(self, operation, changes, **other):
        plan = {"resource_changes": changes, "complete": True, "errored": False, "applyable": True, **other}
        result = subprocess.run([
            "jq", "-e", "--arg", "operation", operation, "--arg", "project", "lab",
            "--arg", "zone", "zone", "--arg", "cluster", "cluster", "-f", ROOT / "scripts/serving-plan.jq",
        ], input=json.dumps(plan), text=True, capture_output=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode == 0

    def test_create_and_delete(self):
        for op in ("create", "delete"):
            before, after = (None, IDENTITY) if op == "create" else (IDENTITY, None)
            change = {"mode": "managed", "address": POOL, "change": {"actions": [op], "before": before, "after": after}}
            platform = {"mode": "managed", "address": "google_container_node_pool.cpu", "change": {"actions": ["no-op"]}}
            with self.subTest(op=op):
                self.assertTrue(self.accepted(op, [change, platform]))
                for action in (["update"], ["delete"], ["delete", "create"]):
                    platform["change"]["actions"] = action
                    self.assertFalse(self.accepted(op, [change, platform]))
                self.assertFalse(self.accepted(op, [change], resource_drift=[platform]))
                self.assertFalse(self.accepted(op, [change], deferred_changes=[{}]))
                self.assertFalse(self.accepted(op, [change], action_invocations=[{}]))
                self.assertFalse(self.accepted(op, [change], output_changes={"cluster_id": {"actions": ["update"]}}))
                platform["change"]["actions"] = ["no-op"]
                platform["previous_address"] = "google_container_node_pool.old"
                self.assertFalse(self.accepted(op, [change, platform]))
                change["change"]["after" if op == "create" else "before"] = {**IDENTITY, "cluster": "wrong"}
                self.assertFalse(self.accepted(op, [change]))
                change["change"]["actions"] = ["delete", "create"]
                self.assertFalse(self.accepted(op, [change]))
