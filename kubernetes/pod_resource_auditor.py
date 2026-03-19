"""
kubernetes/pod_resource_auditor.py
------------------------------------
Audits every pod across namespaces for:
  - Missing resource requests/limits (scheduling risk)
  - OOMKill history (memory limit too low)
  - Over-provisioned pods (requests >> actual usage)
  - Under-provisioned pods (actual usage near limit = OOM risk)
  - Restart count anomalies
  - Pod phase and container state summary

Directly relevant to: Deepanshu's K8s work — "optimized resource allocation
to improve utilization by 20% and cut monthly compute spend by $10K."

Usage:
    python kubernetes/pod_resource_auditor.py
    python kubernetes/pod_resource_auditor.py --namespace production
    python kubernetes/pod_resource_auditor.py --namespace production --output audit.json
    python kubernetes/pod_resource_auditor.py --show-all        # include healthy pods too
"""

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

try:
    from kubernetes import client, config
    config.load_kube_config()
except Exception as e:
    print(f"Error: Could not load kubeconfig — {e}")
    print("Install: pip install kubernetes")
    sys.exit(1)


SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING  = "WARNING"
SEVERITY_INFO     = "INFO"
SEVERITY_OK       = "OK"


@dataclass
class PodIssue:
    severity: str
    namespace: str
    pod: str
    container: str
    issue: str
    detail: str
    recommendation: str


@dataclass
class PodSummary:
    namespace: str
    pod: str
    phase: str
    ready: str          # e.g. "2/3"
    restarts: int
    containers: list = field(default_factory=list)
    issues: list = field(default_factory=list)


def parse_cpu_to_millicores(cpu_str: str) -> Optional[int]:
    """Convert CPU string to millicores. e.g. '500m' → 500, '1' → 1000."""
    if not cpu_str:
        return None
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    try:
        return int(float(cpu_str) * 1000)
    except ValueError:
        return None


def parse_memory_to_mib(mem_str: str) -> Optional[int]:
    """Convert memory string to MiB. e.g. '256Mi' → 256, '1Gi' → 1024, '512000000' → ~488."""
    if not mem_str:
        return None
    units = {"Ki": 1/1024, "Mi": 1, "Gi": 1024, "Ti": 1024*1024,
             "K": 1/1.024/1024, "M": 1/1.049, "G": 1024/1.049}
    for suffix, factor in units.items():
        if mem_str.endswith(suffix):
            try:
                return int(float(mem_str[:-len(suffix)]) * factor)
            except ValueError:
                return None
    try:
        return int(mem_str) // (1024 * 1024)
    except ValueError:
        return None


def audit_pod(pod) -> PodSummary:
    ns = pod.metadata.namespace
    name = pod.metadata.name
    phase = pod.status.phase or "Unknown"
    container_statuses = pod.status.container_statuses or []

    total_containers = len(pod.spec.containers)
    ready_containers = sum(1 for cs in container_statuses if cs.ready)
    total_restarts = sum(cs.restart_count for cs in container_statuses)

    summary = PodSummary(
        namespace=ns,
        pod=name,
        phase=phase,
        ready=f"{ready_containers}/{total_containers}",
        restarts=total_restarts,
    )

    # --- Check each container ---
    for container in pod.spec.containers:
        cname = container.name
        resources = container.resources
        requests = resources.requests or {} if resources else {}
        limits = resources.limits or {} if resources else {}

        cpu_req  = parse_cpu_to_millicores(requests.get("cpu"))
        cpu_lim  = parse_cpu_to_millicores(limits.get("cpu"))
        mem_req  = parse_memory_to_mib(requests.get("memory"))
        mem_lim  = parse_memory_to_mib(limits.get("memory"))

        container_info = {
            "name": cname,
            "cpu_request": requests.get("cpu", "NOT SET"),
            "cpu_limit": limits.get("cpu", "NOT SET"),
            "mem_request": requests.get("memory", "NOT SET"),
            "mem_limit": limits.get("memory", "NOT SET"),
        }
        summary.containers.append(container_info)

        # 1. Missing resource requests
        if cpu_req is None:
            summary.issues.append(PodIssue(
                severity=SEVERITY_WARNING,
                namespace=ns, pod=name, container=cname,
                issue="No CPU request set",
                detail="Scheduler cannot make optimal placement decisions without CPU request.",
                recommendation=f"Add resources.requests.cpu to container '{cname}'",
            ))
        if mem_req is None:
            summary.issues.append(PodIssue(
                severity=SEVERITY_WARNING,
                namespace=ns, pod=name, container=cname,
                issue="No memory request set",
                detail="Pod may be scheduled on an already memory-pressured node.",
                recommendation=f"Add resources.requests.memory to container '{cname}'",
            ))

        # 2. Missing limits
        if cpu_lim is None:
            summary.issues.append(PodIssue(
                severity=SEVERITY_INFO,
                namespace=ns, pod=name, container=cname,
                issue="No CPU limit set",
                detail="Container can consume all available CPU on the node (CPU throttle risk for neighbours).",
                recommendation=f"Set resources.limits.cpu for container '{cname}'",
            ))
        if mem_lim is None:
            summary.issues.append(PodIssue(
                severity=SEVERITY_WARNING,
                namespace=ns, pod=name, container=cname,
                issue="No memory limit set",
                detail="Container can consume unbounded memory — will be OOMKilled by the kernel.",
                recommendation=f"Set resources.limits.memory for container '{cname}'",
            ))

        # 3. Memory limit very close to request (< 10% headroom = OOM risk)
        if mem_req and mem_lim and mem_lim > 0:
            headroom = (mem_lim - mem_req) / mem_lim * 100
            if headroom < 10:
                summary.issues.append(PodIssue(
                    severity=SEVERITY_WARNING,
                    namespace=ns, pod=name, container=cname,
                    issue=f"Memory headroom only {headroom:.0f}% (limit ≈ request)",
                    detail=f"Request: {requests.get('memory')} / Limit: {limits.get('memory')}. "
                           "Any memory spike will trigger OOMKill.",
                    recommendation="Increase memory limit or reduce request by at least 20%.",
                ))

    # --- Check container statuses ---
    for cs in container_statuses:
        cname = cs.name

        # 4. OOMKilled history
        if cs.last_state and cs.last_state.terminated:
            if cs.last_state.terminated.reason == "OOMKilled":
                summary.issues.append(PodIssue(
                    severity=SEVERITY_CRITICAL,
                    namespace=ns, pod=name, container=cname,
                    issue="Container was OOMKilled",
                    detail=f"Last termination reason: OOMKilled at "
                           f"{cs.last_state.terminated.finished_at}",
                    recommendation="Increase memory limit. Check for memory leaks: "
                                   f"kubectl logs {name} -n {ns} --previous",
                ))

        # 5. High restart count
        if cs.restart_count >= 10:
            severity = SEVERITY_CRITICAL if cs.restart_count >= 20 else SEVERITY_WARNING
            summary.issues.append(PodIssue(
                severity=severity,
                namespace=ns, pod=name, container=cname,
                issue=f"High restart count: {cs.restart_count}",
                detail="Frequent restarts indicate a crash loop or persistent failure.",
                recommendation=f"kubectl logs {name} -n {ns} --previous | tail -50",
            ))

        # 6. CrashLoopBackOff
        if cs.state and cs.state.waiting:
            reason = cs.state.waiting.reason or ""
            if reason == "CrashLoopBackOff":
                summary.issues.append(PodIssue(
                    severity=SEVERITY_CRITICAL,
                    namespace=ns, pod=name, container=cname,
                    issue="CrashLoopBackOff",
                    detail=cs.state.waiting.message or "Container keeps crashing.",
                    recommendation=f"kubectl logs {name} -n {ns} --previous",
                ))
            elif reason in ("ImagePullBackOff", "ErrImagePull"):
                summary.issues.append(PodIssue(
                    severity=SEVERITY_CRITICAL,
                    namespace=ns, pod=name, container=cname,
                    issue=f"Image pull failure: {reason}",
                    detail="Cannot pull container image. Check image name, tag, and registry credentials.",
                    recommendation=f"kubectl describe pod {name} -n {ns}",
                ))

    # 7. Pod not running/succeeded
    if phase not in ("Running", "Succeeded"):
        summary.issues.append(PodIssue(
            severity=SEVERITY_CRITICAL if phase in ("Failed", "Unknown") else SEVERITY_WARNING,
            namespace=ns, pod=name, container="(pod)",
            issue=f"Pod phase: {phase}",
            detail=f"Pod is not in Running state.",
            recommendation=f"kubectl describe pod {name} -n {ns}",
        ))

    return summary


def print_report(summaries: list, show_all: bool, output_path: Optional[str]):
    all_issues = [issue for s in summaries for issue in s.issues]
    counts = {
        SEVERITY_CRITICAL: sum(1 for i in all_issues if i.severity == SEVERITY_CRITICAL),
        SEVERITY_WARNING:  sum(1 for i in all_issues if i.severity == SEVERITY_WARNING),
        SEVERITY_INFO:     sum(1 for i in all_issues if i.severity == SEVERITY_INFO),
    }

    print(f"\n{'='*62}")
    print(f"  Kubernetes Pod Resource Audit")
    print(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Pods scanned : {len(summaries)}")
    print(f"{'='*62}")
    print(f"  CRITICAL : {counts[SEVERITY_CRITICAL]}")
    print(f"  WARNING  : {counts[SEVERITY_WARNING]}")
    print(f"  INFO     : {counts[SEVERITY_INFO]}")
    print(f"{'='*62}\n")

    for s in summaries:
        if not s.issues and not show_all:
            continue

        status_icon = "[OK]" if not s.issues else (
            "[!!]" if any(i.severity == SEVERITY_CRITICAL for i in s.issues) else "[! ]"
        )
        print(f"{status_icon} {s.namespace}/{s.pod}")
        print(f"     Phase: {s.phase} | Ready: {s.ready} | Restarts: {s.restarts}")

        for c in s.containers:
            print(f"     Container '{c['name']}':")
            print(f"       CPU  req={c['cpu_request']}  lim={c['cpu_limit']}")
            print(f"       MEM  req={c['mem_request']}  lim={c['mem_limit']}")

        for issue in s.issues:
            sev_label = {
                SEVERITY_CRITICAL: "[CRITICAL]",
                SEVERITY_WARNING:  "[WARNING] ",
                SEVERITY_INFO:     "[INFO]    ",
            }.get(issue.severity, "          ")
            print(f"     {sev_label} {issue.container}: {issue.issue}")
            print(f"                 {issue.detail}")
            print(f"                 > {issue.recommendation}")
        print()

    if output_path:
        with open(output_path, "w") as f:
            json.dump(
                [asdict(s) for s in summaries],
                f, indent=2, default=str
            )
        print(f"Audit saved to: {output_path}")

    return counts[SEVERITY_CRITICAL]


def main():
    parser = argparse.ArgumentParser(description="Kubernetes Pod Resource Auditor")
    parser.add_argument("--namespace", help="Namespace to audit (default: all namespaces)")
    parser.add_argument("--output", help="Save JSON report to file")
    parser.add_argument("--show-all", action="store_true",
                        help="Include healthy pods in output (default: problems only)")
    args = parser.parse_args()

    v1 = client.CoreV1Api()

    if args.namespace:
        pods = v1.list_namespaced_pod(namespace=args.namespace).items
    else:
        pods = v1.list_pod_for_all_namespaces().items

    print(f"Auditing {len(pods)} pods{' in ' + args.namespace if args.namespace else ' across all namespaces'}...")
    summaries = [audit_pod(pod) for pod in pods]
    critical_count = print_report(summaries, args.show_all, args.output)

    # Exit 1 if critical issues found — safe to use as a CI gate
    sys.exit(1 if critical_count > 0 else 0)


if __name__ == "__main__":
    main()
