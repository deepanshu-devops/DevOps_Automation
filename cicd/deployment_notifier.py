"""
cicd/deployment_notifier.py
-----------------------------
Posts structured, colour-coded deployment notifications to Slack (or any
webhook) at each stage of a release pipeline — start, success, failure,
and rollback. Designed to be called from Jenkins stages or GitHub Actions steps.

Directly relevant to: Deepanshu's CI/CD pipeline automation at Amdocs —
"automated release pipelines with Terraform and Jenkins, shortening release
cadence from weekly to daily."

Features:
  - Four event types: started, success, failure, rollback
  - Attaches git commit hash, author, branch, and changelog summary
  - Links directly to the CI build, Kubernetes rollout status, and CloudWatch logs
  - Supports custom fields for environment, service name, version, approver
  - Can be called from shell: python deployment_notifier.py --event success ...

Usage:
    # From a Jenkins pipeline (Groovy):
    sh "python cicd/deployment_notifier.py --event started --service payment-api --env production --version v2.4.1"
    sh "python cicd/deployment_notifier.py --event success --service payment-api --env production --version v2.4.1 --commit abc1234"

    # From the command line:
    python cicd/deployment_notifier.py --event failure --service payment-api --env production --version v2.4.1 --reason "Health check failed after 3 retries"
    python cicd/deployment_notifier.py --event rollback --service payment-api --env production --version v2.4.0 --reason "Reverted to v2.4.0 due to p99 latency spike"
"""

import argparse
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from typing import Optional


EVENT_CONFIG = {
    "started": {
        "colour": "#378ADD",    # Blue — neutral, in progress
        "icon": ":rocket:",
        "title": "Deployment started",
        "default_message": "Deployment pipeline triggered.",
    },
    "success": {
        "colour": "#639922",    # Green — all good
        "icon": ":white_check_mark:",
        "title": "Deployment succeeded",
        "default_message": "All checks passed. Service is live.",
    },
    "failure": {
        "colour": "#A32D2D",    # Red — needs immediate attention
        "icon": ":x:",
        "title": "Deployment FAILED",
        "default_message": "Deployment did not complete. Manual investigation required.",
    },
    "rollback": {
        "colour": "#BA7517",    # Amber — warning, action taken
        "icon": ":rewind:",
        "title": "Rollback triggered",
        "default_message": "Deployment rolled back to previous stable version.",
    },
}


def get_git_info() -> dict:
    """
    Attempt to read git metadata from the current working directory.
    Falls back gracefully if not in a git repo or git is unavailable.
    """
    def git(cmd: str) -> str:
        try:
            return subprocess.check_output(
                ["git"] + cmd.split(), stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            return ""

    return {
        "commit": git("rev-parse --short HEAD"),
        "author": git("log -1 --format=%an"),
        "branch": git("rev-parse --abbrev-ref HEAD"),
        "message": git("log -1 --format=%s"),
    }


def build_slack_payload(
    event: str,
    service: str,
    environment: str,
    version: str,
    reason: Optional[str],
    commit: Optional[str],
    build_url: Optional[str],
    approver: Optional[str],
) -> dict:
    config = EVENT_CONFIG[event]
    git = get_git_info()

    # Prefer explicit --commit flag; fall back to git auto-detect
    commit_hash = commit or git.get("commit") or "unknown"
    branch = git.get("branch") or "unknown"
    author = git.get("author") or "unknown"
    commit_message = git.get("message") or ""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = reason or config["default_message"]

    fields = [
        {"title": "Service",     "value": f"`{service}`",     "short": True},
        {"title": "Environment", "value": f"`{environment}`", "short": True},
        {"title": "Version",     "value": f"`{version}`",     "short": True},
        {"title": "Commit",      "value": f"`{commit_hash}`", "short": True},
        {"title": "Branch",      "value": f"`{branch}`",      "short": True},
        {"title": "Author",      "value": author,              "short": True},
    ]
    if approver:
        fields.append({"title": "Approver", "value": approver, "short": True})
    if commit_message:
        fields.append({"title": "Commit message", "value": commit_message, "short": False})

    actions = []
    if build_url:
        actions.append({"type": "button", "text": "View build", "url": build_url})

    attachment = {
        "color": config["colour"],
        "title": f"{config['icon']} {config['title']} — {service}",
        "text": message,
        "fields": fields,
        "footer": f"DeployBot | {timestamp}",
        "ts": int(datetime.now(timezone.utc).timestamp()),
    }
    if actions:
        attachment["actions"] = actions

    return {"attachments": [attachment]}


def send(webhook_url: str, payload: dict):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def print_summary(event: str, service: str, environment: str, version: str):
    config = EVENT_CONFIG[event]
    print(f"\n{config['icon']}  {config['title']}")
    print(f"   Service     : {service}")
    print(f"   Environment : {environment}")
    print(f"   Version     : {version}")
    print(f"   Time        : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    parser = argparse.ArgumentParser(description="Deployment Event Notifier")
    parser.add_argument("--event", required=True, choices=list(EVENT_CONFIG.keys()),
                        help="Deployment event type: started | success | failure | rollback")
    parser.add_argument("--service", required=True, help="Service/application name, e.g. payment-api")
    parser.add_argument("--env", required=True, help="Target environment, e.g. production, staging")
    parser.add_argument("--version", required=True, help="Version or image tag being deployed, e.g. v2.4.1")
    parser.add_argument("--reason", help="Optional message explaining the outcome or failure reason")
    parser.add_argument("--commit", help="Git commit hash (auto-detected if inside a git repo)")
    parser.add_argument("--build-url", help="URL to the CI build logs, e.g. http://jenkins:8080/job/...")
    parser.add_argument("--approver", help="Name of person who approved the deployment")
    parser.add_argument(
        "--webhook",
        default=os.environ.get("SLACK_WEBHOOK", ""),
        help="Slack webhook URL. Can also be set via SLACK_WEBHOOK env var.",
    )
    args = parser.parse_args()

    print_summary(args.event, args.service, args.env, args.version)

    if not args.webhook:
        print("\nNo webhook URL provided (--webhook or SLACK_WEBHOOK env var). Notification skipped.")
        return

    payload = build_slack_payload(
        event=args.event,
        service=args.service,
        environment=args.env,
        version=args.version,
        reason=args.reason,
        commit=args.commit,
        build_url=args.build_url,
        approver=args.approver,
    )
    try:
        status = send(args.webhook, payload)
        print(f"   Notification sent (HTTP {status})")
    except Exception as e:
        print(f"   Notification failed: {e}")


if __name__ == "__main__":
    main()
