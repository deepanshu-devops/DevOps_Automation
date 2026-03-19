"""
cicd/jenkins_pipeline_monitor.py
----------------------------------
Polls the Jenkins API to detect failed, unstable, or stuck (hung) pipelines
and sends structured Slack alerts with direct links to the failing build logs.

Directly relevant to: Deepanshu's CI/CD experience with Jenkins pipelines
and eliminating 40% of manual tasks via automation at Amdocs.

Features:
  - Monitors all jobs or a filtered list across multiple folders/views
  - Detects: FAILURE, UNSTABLE, hung builds (running beyond timeout threshold)
  - Calculates failure rate trend over last N builds per job
  - Posts colour-coded Slack alert with job name, duration, cause, and log URL
  - Can be run as a cron job or Jenkins pipeline health-check stage

Usage:
    python cicd/jenkins_pipeline_monitor.py --url http://jenkins:8080 --token YOUR_API_TOKEN
    python cicd/jenkins_pipeline_monitor.py --url http://jenkins:8080 --token TOKEN --slack-webhook https://hooks.slack.com/...
    python cicd/jenkins_pipeline_monitor.py --url http://jenkins:8080 --token TOKEN --job-filter "deploy-*" --hung-threshold 60
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import base64
from datetime import datetime, timezone
from typing import Optional


class JenkinsClient:
    def __init__(self, base_url: str, user: str, token: str):
        self.base_url = base_url.rstrip("/")
        credentials = base64.b64encode(f"{user}:{token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }

    def get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"  Jenkins API error [{url}]: {e}")
            return {}

    def get_all_jobs(self) -> list:
        """Recursively fetch all jobs including those inside folders."""
        data = self.get("/api/json?tree=jobs[name,url,jobs[name,url,jobs[name,url]]]")
        return self._flatten_jobs(data.get("jobs", []))

    def _flatten_jobs(self, jobs: list, depth: int = 0) -> list:
        result = []
        for job in jobs:
            if "jobs" in job:
                result.extend(self._flatten_jobs(job["jobs"], depth + 1))
            else:
                result.append(job)
        return result

    def get_last_build(self, job_url: str) -> dict:
        path = job_url.replace(self.base_url, "") + "lastBuild/api/json"
        return self.get(path)

    def get_build_history(self, job_url: str, count: int = 5) -> list:
        path = (
            job_url.replace(self.base_url, "")
            + f"api/json?tree=builds[number,result,duration,timestamp]{{0,{count}}}"
        )
        data = self.get(path)
        return data.get("builds", [])


def ms_to_human(ms: int) -> str:
    """Convert milliseconds to a human-readable duration string."""
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def failure_rate(builds: list) -> float:
    """Calculate failure rate as a percentage over the last N builds."""
    if not builds:
        return 0.0
    failed = sum(1 for b in builds if b.get("result") in ("FAILURE", "UNSTABLE"))
    return round(failed / len(builds) * 100, 1)


def check_job(client: JenkinsClient, job: dict, hung_threshold_min: int) -> Optional[dict]:
    """
    Check a single job's last build status.
    Returns a problem dict if the job needs attention, else None.
    """
    job_name = job.get("name", "unknown")
    job_url = job.get("url", "")
    build = client.get_last_build(job_url)

    if not build:
        return None

    result = build.get("result")          # SUCCESS, FAILURE, UNSTABLE, ABORTED, or None (still running)
    building = build.get("building", False)
    duration_ms = build.get("duration", 0)
    timestamp_ms = build.get("timestamp", 0)
    build_number = build.get("number", "?")
    build_url = build.get("url", job_url)

    problem = None

    if result in ("FAILURE", "UNSTABLE"):
        history = client.get_build_history(job_url)
        rate = failure_rate(history)
        causes = build.get("causes", [{}])
        cause_text = causes[0].get("shortDescription", "Unknown") if causes else "Unknown"
        problem = {
            "job": job_name,
            "status": result,
            "build_number": build_number,
            "build_url": build_url,
            "duration": ms_to_human(duration_ms),
            "cause": cause_text,
            "failure_rate_last5": f"{rate}%",
            "type": "failed",
        }

    elif building:
        # Detect hung builds: still running beyond threshold
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        running_ms = now_ms - timestamp_ms
        running_min = running_ms // 60000
        if running_min > hung_threshold_min:
            problem = {
                "job": job_name,
                "status": "HUNG",
                "build_number": build_number,
                "build_url": build_url,
                "duration": f"{running_min}m (still running)",
                "cause": f"Exceeded {hung_threshold_min}min threshold",
                "failure_rate_last5": "N/A",
                "type": "hung",
            }

    return problem


def send_slack_alert(webhook_url: str, problems: list, jenkins_url: str):
    if not problems:
        return
    lines = [
        f"*Jenkins Pipeline Monitor* — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Jenkins: `{jenkins_url}`",
        f"Issues found: *{len(problems)}*\n",
    ]
    for p in problems:
        icon = ":fire:" if p["status"] == "FAILURE" else ":warning:"
        lines.append(
            f"{icon} *{p['job']}* — `{p['status']}` (Build #{p['build_number']})\n"
            f"   Duration: {p['duration']} | Cause: {p['cause']}\n"
            f"   Failure rate (last 5): {p['failure_rate_last5']}\n"
            f"   <{p['build_url']}console|View build log>"
        )
    payload = json.dumps({"text": "\n".join(lines)}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10)


def main():
    parser = argparse.ArgumentParser(description="Jenkins Pipeline Health Monitor")
    parser.add_argument("--url", required=True, help="Jenkins base URL, e.g. http://jenkins:8080")
    parser.add_argument("--user", default="admin", help="Jenkins username")
    parser.add_argument("--token", required=True, help="Jenkins API token")
    parser.add_argument("--job-filter", default="", help="Filter job names by prefix, e.g. 'deploy-'")
    parser.add_argument("--hung-threshold", type=int, default=60,
                        help="Minutes before a running build is flagged as hung (default: 60)")
    parser.add_argument("--slack-webhook", help="Slack webhook URL for alerts")
    args = parser.parse_args()

    client = JenkinsClient(args.url, args.user, args.token)
    print(f"\nJenkins Pipeline Monitor")
    print(f"{'='*55}")
    print(f"Jenkins URL : {args.url}")
    print(f"Job filter  : '{args.job_filter}' (blank = all jobs)")
    print(f"Hung threshold: {args.hung_threshold} minutes\n")

    jobs = client.get_all_jobs()
    if args.job_filter:
        jobs = [j for j in jobs if j.get("name", "").startswith(args.job_filter)]

    print(f"Jobs to check: {len(jobs)}")
    problems = []

    for job in jobs:
        name = job.get("name", "?")
        problem = check_job(client, job, args.hung_threshold)
        if problem:
            status = problem["status"]
            print(f"  [!] {name}: {status} (Build #{problem['build_number']}) — {problem['duration']}")
            problems.append(problem)
        else:
            print(f"  [OK] {name}")

    print(f"\n{'='*55}")
    print(f"Total jobs checked : {len(jobs)}")
    print(f"Problems found     : {len(problems)}")

    if problems and args.slack_webhook:
        try:
            send_slack_alert(args.slack_webhook, problems, args.url)
            print("Slack alert sent.")
        except Exception as e:
            print(f"Slack alert failed: {e}")

    # Exit 1 if any FAILURE found — allows use as a CI gate
    sys.exit(1 if any(p["type"] == "failed" for p in problems) else 0)


if __name__ == "__main__":
    main()
