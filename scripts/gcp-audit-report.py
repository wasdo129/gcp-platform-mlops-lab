"""Collect selected gcloud fields and write a private, structured inventory."""

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


MEMBER_TYPES = {
    "allUsers", "allAuthenticatedUsers", "deleted", "domain", "group",
    "principal", "principalSet", "serviceAccount", "user",
}


def failure_status(stderr):
    message = stderr.lower()
    if re.search(r"service_disabled|accessnotconfigured|api.+(?:is disabled|not been used)", message):
        return "api_disabled"
    if re.search(r"unauthenticated|no active account|gcloud auth login|invalid_grant|reauthentication", message):
        return "authentication_required"
    if re.search(r"permission_denied|permission|forbidden|access denied|\b403\b", message):
        return "permission_denied"
    if re.search(r"not_found|not found|does not exist|\b404\b", message):
        return "not_found"
    return "command_failed"


def check(command, fields, expected, env, transform=None):
    try:
        result = subprocess.run(
            ["gcloud", *command, "--quiet", "--verbosity=warning", f"--format=json({fields})"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except OSError:
        return {"status": "command_failed"}

    if result.returncode:
        return {"status": failure_status(result.stderr), "exit_code": result.returncode}

    try:
        if expected is list and not result.stdout.strip():
            data = []
        else:
            data = json.loads(result.stdout)
        if not isinstance(data, expected):
            raise ValueError("Unexpected report shape")
        if transform:
            data = transform(data)
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"status": "invalid_output"}

    status = "ok" if data else "empty"
    if re.search(r"\b(warning|error)\b\s*:|partial (?:success|list)|missing zones", result.stderr, re.I):
        status = "warning"
    return {"status": status, "data": data}


def config_summary(data):
    core = data.get("core", {})
    compute = data.get("compute", {})
    return {
        "default_project": core.get("project"),
        "account_configured": bool(core.get("account")),
        "default_region": compute.get("region"),
        "default_zone": compute.get("zone"),
    }


def summarize_bindings(policy):
    bindings = []
    for binding in policy.get("bindings", []):
        member_types = Counter()
        service_accounts = []
        for member in binding["members"]:
            prefix, _, identity = member.partition(":")
            if prefix == "serviceAccount" and re.fullmatch(
                r"[a-zA-Z0-9_.+%-]+@[a-zA-Z0-9.-]+\.gserviceaccount\.com", identity
            ):
                service_accounts.append(identity)
            member_types[prefix if prefix in MEMBER_TYPES else "other"] += 1
        bindings.append({
            "role": binding["role"],
            "conditional": bool(binding.get("condition")),
            "member_types": dict(sorted(member_types.items())),
            "service_accounts": sorted(service_accounts),
        })
    return bindings


def summarize_quotas(region):
    return [
        {key: quota[key] for key in ("metric", "limit", "usage")}
        for quota in region.get("quotas", [])
    ]


def collect(project, region):
    env = {
        **os.environ,
        "LC_ALL": "C",
        "CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK": "true",
        "CLOUDSDK_CORE_DISABLE_FILE_LOGGING": "true",
        "CLOUDSDK_CORE_DISABLE_USAGE_REPORTING": "true",
        "CLOUDSDK_CORE_LOG_HTTP": "false",
        "CLOUDSDK_CORE_SHOW_STRUCTURED_LOGS": "never",
        "CLOUDSDK_CORE_USER_OUTPUT_ENABLED": "true",
    }
    sections = {
        "gcloud_config": check(
            ["config", "list"], "core.project,core.account,compute.region,compute.zone",
            dict, env, config_summary,
        )
    }

    apis = None

    def cloud_check(name, command, fields, expected=list, transform=None, api=None):
        if api and apis is not None and api not in apis:
            sections[name] = {"status": "api_disabled", "api": api}
        else:
            sections[name] = check(
                [*command, f"--project={project}"], fields, expected, env, transform
            )

    cloud_check("project", ["projects", "describe", project],
                "projectId,projectNumber,lifecycleState,createTime,parent.type", dict)
    cloud_check("enabled_apis", ["services", "list", "--enabled"], "config.name",
                transform=lambda services: sorted(service["config"]["name"] for service in services))
    enabled = sections["enabled_apis"]
    apis = set(enabled["data"]) if enabled["status"] in {"ok", "empty"} else None

    cloud_check("project_iam", ["projects", "get-iam-policy", project],
                "bindings", dict, summarize_bindings)
    cloud_check("service_accounts", ["iam", "service-accounts", "list"], "email,disabled",
                api="iam.googleapis.com")
    compute_api = "compute.googleapis.com"
    cloud_check("compute_quotas", ["compute", "regions", "describe", region],
                "quotas", dict, summarize_quotas, compute_api)
    cloud_check("vpc_networks", ["compute", "networks", "list"],
                "name,autoCreateSubnetworks,routingConfig.routingMode", api=compute_api)
    cloud_check("subnets", ["compute", "networks", "subnets", "list"],
                "name,region,network,ipCidrRange,secondaryIpRanges,privateIpGoogleAccess,purpose",
                api=compute_api)
    cloud_check("compute_instances", ["compute", "instances", "list"],
                "name,zone,machineType,status", api=compute_api)
    cloud_check("gke_clusters", ["container", "clusters", "list"],
                "name,location,zone,status,autopilot.enabled,currentMasterVersion,currentNodeCount",
                api="container.googleapis.com")
    return sections


def main(project, region):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        print("Provide a valid Google Cloud project ID.", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[a-z]+(?:-[a-z]+)+[0-9]+", region):
        print("Provide a valid Compute Engine region, for example europe-west3.", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    root = Path(__file__).resolve().parent.parent / ".audit"
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        if root.is_symlink():
            print("The .audit directory must not be a symbolic link.", file=sys.stderr)
            return 1
        run_dir = Path(tempfile.mkdtemp(prefix=now.strftime("%Y%m%dT%H%M%SZ-"), dir=root))
        report_path = run_dir / "report.json"
        sections = collect(project, region)
        with report_path.open("x", encoding="utf-8") as report:
            json.dump({
                "started_at": now.isoformat(),
                "project_id": project,
                "quota_region": region,
                "sections": sections,
            }, report, indent=2)
            report.write("\n")
    except OSError:
        print("Unable to write the audit report.", file=sys.stderr)
        return 1

    for name, section in sections.items():
        print(f"{name}: {section['status']}")
    print(f"Report: {report_path}")
    return 0 if all(section["status"] in {"ok", "empty"} for section in sections.values()) else 2


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
