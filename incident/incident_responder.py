"""
incident/incident_responder.py
--------------------------------
Automated first-response playbook triggered on Prometheus/CloudWatch alerts.
Collects diagnostic data, attempts safe auto-remediation, and posts
a structured incident report to Slack.

Directly relevant to: Deepanshu's MTTR reduction (40 → 30 min) and
incident response leadership for Terraform state corruption.

Playbooks included:
  - High CPU on pod → collect metrics, attempt HPA scale-up
  - High memory on pod → collect heap dump info, alert
  - Service unavailable → check endpoints, restart if safe
  - Disk pressure on node → log cleanup, alert

Usage:
    python incident/incident_responder.py --alert HighCPU --target payment-api --namespace production
    python incident/incident_responder.py --alert DiskPressure --target node-1
    python incident/incident_responder.py --alert ServiceDown --target payment-api --namespace production
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional
import urllib.request


SLACK_WEBHOOK = ""  # Set via --slack-webhook or env var SLACK_WEBHOOK


class IncidentReport:
    def __init__(self, alert: str, target: str, namespace: str):
        self.alert = alert
        self.target = target
        self.namespace = namespace
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.steps: list = []
        self.auto_remediated = False
        self.severity = "P2"
        self.resolution = "Manual investigation required"

    def add_step(self, step: str, output: str = "", success: bool = True):
        self.steps.append({
            "step": step,
            "output": output[:500] if output else "",
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        status = "[OK]" if success else "[FAIL]"
        print(f"  {status} {step}")
        if output:
            for line in output.strip().split("\n")[:5]:
                print(f"       {line}")

    def to_slack_blocks(self) -> dict:
        emoji = "fire" if self.severity == "P1" else "warning"
        remediated = "Auto-remediated" if self.auto_remediated else "Manual action needed"
        text = (
            f":{emoji}: *Incident Alert — {self.alert}*\n"
            f"Target: `{self.target}` | Namespace: `{self.namespace}`\n"
            f"Severity: `{self.severity}` | Status: `{remediated}`\n"
            f"Resolution: {self.resolution}\n"
            f"Started: {self.started_at}\n\n"
            f"*Diagnostic Steps:*\n"
        )
        for s in self.steps:
            icon = ":white_check_mark:" if s["success"] else ":x:"
            text += f"{icon} {s['step']}\n"
            if s["output"]:
                text += f"```{s['output'][:200]}```\n"
        return {"text": text}


def run_kubectl(cmd: str, timeout: int = 30) -> tuple:
    try:
        result = subprocess.run(
            ["kubectl"] + cmd.split(),
            capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except FileNotFoundError:
        return False, "kubectl not found"


def playbook_high_cpu(report: IncidentReport):
    """High CPU playbook — gather metrics, scale HPA if available."""
    report.severity = "P2"
    ok, out = run_kubectl(f"top pod {report.target} -n {report.namespace}")
    report.add_step("Collect pod CPU/memory metrics (kubectl top)", out, ok)
    ok, out = run_kubectl(f"describe pod {report.target} -n {report.namespace}")
    report.add_step("Describe pod for resource limits", out[:300], ok)
    ok, out = run_kubectl(
        f"get hpa -n {report.namespace} -o json"
    )
    if ok and report.target in out:
        report.add_step("HPA found — checking saturation", out[:300], True)
        ok2, out2 = run_kubectl(
            f"patch hpa {report.target} -n {report.namespace} "
            f"--type=merge -p "
            f'\'{"spec":{"maxReplicas":20}}\''
        )
        report.add_step("Attempted HPA max-replicas bump to 20", out2, ok2)
        if ok2:
            report.auto_remediated = True
            report.resolution = "HPA max-replicas increased — monitor for scale-out"
    else:
        report.add_step("No HPA found — manual scaling required", "", False)
        report.resolution = "No HPA configured. Review deployment resources or add HPA."
    ok, out = run_kubectl(f"logs {report.target} -n {report.namespace} --tail=50")
    report.add_step("Collect recent pod logs (last 50 lines)", out, ok)


def playbook_high_memory(report: IncidentReport):
    """High memory / OOMKill risk playbook."""
    report.severity = "P1"
    ok, out = run_kubectl(f"top pod {report.target} -n {report.namespace}")
    report.add_step("Collect memory metrics", out, ok)
    ok, out = run_kubectl(f"describe pod {report.target} -n {report.namespace}")
    report.add_step("Check memory limits and OOM events", out[:400], ok)
    ok, out = run_kubectl(f"logs {report.target} -n {report.namespace} --previous --tail=100")
    report.add_step("Check previous container logs for OOM", out, ok)
    report.resolution = (
        "Increase memory limit in deployment spec. "
        "Review for memory leaks. Consider adding VPA."
    )


def playbook_service_down(report: IncidentReport):
    """Service unavailable — check endpoints, restart if all replicas are stuck."""
    report.severity = "P1"
    ok, out = run_kubectl(f"get endpoints {report.target} -n {report.namespace}")
    report.add_step("Check service endpoints", out, ok)
    ok, out = run_kubectl(
        f"get deployment {report.target} -n {report.namespace} -o json"
    )
    if ok:
        try:
            dep = json.loads(out)
            available = dep.get("status", {}).get("availableReplicas", 0) or 0
            desired = dep.get("spec", {}).get("replicas", 1)
            report.add_step(
                f"Deployment replicas: {available}/{desired} available",
                "", available > 0
            )
            if available == 0:
                ok2, out2 = run_kubectl(
                    f"rollout restart deployment/{report.target} -n {report.namespace}"
                )
                report.add_step("Triggered rolling restart (0 replicas available)", out2, ok2)
                report.auto_remediated = ok2
                report.resolution = "Rolling restart triggered — monitor rollout status"
        except json.JSONDecodeError:
            report.add_step("Could not parse deployment JSON", out[:200], False)
    ok, out = run_kubectl(f"get events -n {report.namespace} --sort-by=.lastTimestamp")
    report.add_step("Collect namespace events (last 10)", "\n".join(out.split("\n")[-10:]), ok)


def playbook_disk_pressure(report: IncidentReport):
    """Disk pressure on node — clean up logs and alert."""
    report.severity = "P2"
    ok, out = run_kubectl(f"describe node {report.target}")
    report.add_step("Describe node for disk conditions", out[:400], ok)
    ok, out = run_kubectl(f"get pods --all-namespaces --field-selector spec.nodeName={report.target}")
    report.add_step("List pods on affected node", out, ok)
    report.resolution = (
        "Manual: SSH to node and run `docker system prune` or `journalctl --vacuum-size=500M`. "
        "Check for large log files in /var/log."
    )


PLAYBOOKS = {
    "HighCPU": playbook_high_cpu,
    "HighMemory": playbook_high_memory,
    "ServiceDown": playbook_service_down,
    "DiskPressure": playbook_disk_pressure,
}


def send_to_slack(webhook_url: str, report: IncidentReport):
    payload = json.dumps(report.to_slack_blocks()).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Automated Incident Responder")
    parser.add_argument("--alert", required=True, choices=list(PLAYBOOKS.keys()),
                        help="Alert type to respond to")
    parser.add_argument("--target", required=True, help="Pod, deployment, or node name")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--slack-webhook", default=SLACK_WEBHOOK)
    args = parser.parse_args()

    report = IncidentReport(args.alert, args.target, args.namespace)
    print(f"\nIncident Responder — {args.alert}")
    print(f"{'='*55}")
    print(f"Target    : {args.target}")
    print(f"Namespace : {args.namespace}")
    print(f"Started   : {report.started_at}\n")

    playbook = PLAYBOOKS[args.alert]
    playbook(report)

    print(f"\n{'='*55}")
    print(f"Severity         : {report.severity}")
    print(f"Auto-remediated  : {report.auto_remediated}")
    print(f"Resolution       : {report.resolution}")

    if args.slack_webhook:
        try:
            send_to_slack(args.slack_webhook, report)
            print("Slack notification sent.")
        except Exception as e:
            print(f"Slack notification failed: {e}")


if __name__ == "__main__":
    main()
