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
            "jq", "-L", str(ROOT / "scripts"), "-e", "--arg", "operation", operation, "--arg", "project", "lab",
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

    def test_baseline_requires_no_managed_actions(self):
        command = [
            "jq", "-L", str(ROOT / "scripts"), "-e",
            'include "serving-drift"; serving_baseline_clean("lab"; "zone"; "cluster")',
        ]
        plan = {"complete": True, "errored": False, "applyable": False, "resource_changes": [
            {"mode": "managed", "address": "google_container_node_pool.cpu", "change": {"actions": ["no-op"]}},
        ]}
        for action, expected in (("no-op", 0), ("create", 1), ("update", 1), ("delete", 1)):
            with self.subTest(action=action):
                plan["resource_changes"][0]["change"]["actions"] = [action]
                result = subprocess.run(command, input=json.dumps(plan), text=True, capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_exact_read_side_drift_and_rejected_mutations(self):
        legacy = json.loads((ROOT / "scripts/serving-cluster-read.json").read_text())
        cluster_before = {"project": "lab", "location": "zone", "name": "cluster", "node_config": [], "node_pool": []}
        cluster_after = {
            **cluster_before, "node_config": legacy["node_config"],
            "node_pool": [{**pool, "node_config": legacy["node_config"]} for pool in legacy["node_pool"]],
        }
        cpu_before = {**IDENTITY, "name": "cpu", "node_config": [{
            "resource_manager_tags": None, "storage_pools": None, "machine_type": "e2-standard-2",
            "tags": ["llmops-lab-node"], "service_account": "expected@example.test",
        }]}
        cpu_after = copy.deepcopy(cpu_before)
        cpu_after["node_config"][0].update(resource_manager_tags={}, storage_pools=[])
        firewall_before = {
            "project": "lab", "name": "cluster-cnpg-webhook", "source_ranges": ["10.46.0.0/28"],
            "allow": [{"protocol": "tcp", "ports": ["9443"]}], "target_tags": ["llmops-lab-node"],
            "source_tags": None, "source_service_accounts": None, "target_service_accounts": None,
        }
        firewall_after = {
            **firewall_before, "source_tags": [], "source_service_accounts": [], "target_service_accounts": [],
        }
        drift = [
            {"address": address, "mode": "managed", "provider_name": "registry.terraform.io/hashicorp/google",
             "change": {"actions": ["update"], "before": before, "after": after}}
            for address, before, after in (
                ("google_container_cluster.lab", cluster_before, cluster_after),
                ("google_container_node_pool.cpu", cpu_before, cpu_after),
                ("google_compute_firewall.cnpg_webhook", firewall_before, firewall_after),
            )
        ]
        mutations = (
            (2, ("source_ranges",), ["0.0.0.0/0"]),
            (2, ("allow", 0, "ports"), ["22"]),
            (2, ("target_tags",), ["wrong"]),
            (2, ("source_tags",), ["wrong"]),
            (1, ("node_config", 0, "tags"), []),
            (1, ("node_config", 0, "machine_type"), "e2-standard-4"),
            (1, ("node_config", 0, "service_account"), "wrong@example.test"),
            (1, ("name",), "wrong"),
            (0, ("node_pool", 0, "name"), "wrong"),
            (0, ("node_pool", 0, "node_config", 0, "unknown"), True),
            (0, ("node_config", 0, "service_account"), "wrong@example.test"),
            (0, ("node_config", 0, "machine_type"), "e2-standard-4"),
            (0, ("new_field",), True),
        )
        for operation, before, after in (("create", None, IDENTITY), ("delete", IDENTITY, None)):
            change = {"mode": "managed", "address": POOL,
                      "change": {"actions": [operation], "before": before, "after": after}}
            self.assertTrue(self.accepted(operation, [change], resource_drift=drift))
            for index, parts, value in mutations:
                with self.subTest(operation=operation, path=parts):
                    changed = copy.deepcopy(drift)
                    target = copy.deepcopy(changed[index]["change"]["after"])
                    changed[index]["change"]["after"] = target
                    for part in parts[:-1]:
                        target = target[part]
                    target[parts[-1]] = value
                    self.assertFalse(self.accepted(operation, [change], resource_drift=changed))
