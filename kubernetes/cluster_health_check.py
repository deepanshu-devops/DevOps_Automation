"""
kubernetes/cluster_health_check.py
------------------------------------
Comprehensive Kubernetes cluster health reporter.
Checks node status, pod health, resource pressure, PVC bindings,
failing deployments, and HPA saturation.

Directly relevant to: Deepanshu's management of 200K+ concurrent sessions
and 1M+ daily transactions on OpenShift/EKS clusters.

Usage:
    python kubernetes/cluster_health_check.py
    python kubernetes/cluster_health_check.py --namespace production
    python kubernetes/cluster_health_check.py --namespace production --output report.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List, Optional

try:
    from kubernetes import client, config
    config.load_kube_config()
except Exception:
    print("Warning: kubernetes config not found. Install: pip install kubernetes")
    sys.exit(1)


SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING  = "WARNING"
SEVERITY_OK       = "OK"


@dataclass
class HealthIssue:
    severity: str
    category: str
    resource: str
    namespace: str
    message: str
    recommendation: str


def check_nodes(v1) -> List[HealthIssue]:
    issues = []
    nodes = v1.list_node().items
    for node in nodes:
        name = node.metadata.name
        conditions = {c.type: c for c in node.status.conditions}
        ready = conditions.get("Ready")
        if ready and ready.status != "True":
            issues.append(HealthIssue(
                severity=SEVERITY_CRITICAL,
                category="Node",
                resource=name,
                namespace="cluster",
                message=f"Node not ready: {ready.message}",
                recommendation="Investigate node: kubectl describe node " + name,
            ))
        for pressure in ("MemoryPressure", "DiskPressure", "PIDPressure"):
            cond = conditions.get(pressure)
            if cond and cond.status == "True":
                issues.append(HealthIssue(
                    severity=SEVERITY_WARNING,
                    category="Node",
                    resource=name,
                    namespace="cluster",
                    message=f"{pressure} detected on node",
                    recommendation=f"Check resource usage: kubectl top node {name}",
                ))
    if not issues:
        issues.append(HealthIssue(
            severity=SEVERITY_OK,
            category="Node",
            resource=f"All {len(nodes)} nodes",
            namespace="cluster",
            message="All nodes healthy",
            recommendation="",
        ))
    return issues


def check_pods(v1, namespace: Optional[str]) -> List[HealthIssue]:
    issues = []
    kwargs = {"namespace": namespace} if namespace else {}
    pods = v1.list_namespaced_pod(**kwargs).items if namespace else v1.list_pod_for_all_namespaces().items
    crash_looping, pending, oom_killed = [], [], []
    for pod in pods:
        ns = pod.metadata.namespace
        name = pod.metadata.name
        phase = pod.status.phase
        if phase == "Pending":
            pending.append((ns, name))
        for cs in (pod.status.container_statuses or []):
            if cs.state.waiting and cs.state.waiting.reason == "CrashLoopBackOff":
                crash_looping.append((ns, name, cs.restart_count))
            if cs.last_state.terminated and cs.last_state.terminated.reason == "OOMKilled":
                oom_killed.append((ns, name))
    for ns, name, restarts in crash_looping:
        issues.append(HealthIssue(
            severity=SEVERITY_CRITICAL,
            category="Pod",
            resource=name,
            namespace=ns,
            message=f"CrashLoopBackOff — {restarts} restarts",
            recommendation=f"kubectl logs {name} -n {ns} --previous",
        ))
    for ns, name in pending:
        issues.append(HealthIssue(
            severity=SEVERITY_WARNING,
            category="Pod",
            resource=name,
            namespace=ns,
            message="Pod stuck in Pending state",
            recommendation=f"kubectl describe pod {name} -n {ns} (check events for scheduling issues)",
        ))
    for ns, name in oom_killed:
        issues.append(HealthIssue(
            severity=SEVERITY_WARNING,
            category="Pod",
            resource=name,
            namespace=ns,
            message="Container was OOMKilled — memory limit too low",
            recommendation="Increase memory limit in deployment spec or investigate memory leak",
        ))
    return issues


def check_deployments(apps_v1, namespace: Optional[str]) -> List[HealthIssue]:
    issues = []
    deployments = (
        apps_v1.list_namespaced_deployment(namespace=namespace).items
        if namespace
        else apps_v1.list_deployment_for_all_namespaces().items
    )
    for dep in deployments:
        ns = dep.metadata.namespace
        name = dep.metadata.name
        desired = dep.spec.replicas or 0
        available = dep.status.available_replicas or 0
        ready = dep.status.ready_replicas or 0
        if available < desired:
            issues.append(HealthIssue(
                severity=SEVERITY_CRITICAL if available == 0 else SEVERITY_WARNING,
                category="Deployment",
                resource=name,
                namespace=ns,
                message=f"Unavailable replicas: {available}/{desired} ready, {ready} up",
                recommendation=f"kubectl rollout status deployment/{name} -n {ns}",
            ))
    return issues


def check_pvcs(v1, namespace: Optional[str]) -> List[HealthIssue]:
    issues = []
    pvcs = (
        v1.list_namespaced_persistent_volume_claim(namespace=namespace).items
        if namespace
        else v1.list_persistent_volume_claim_for_all_namespaces().items
    )
    for pvc in pvcs:
        if pvc.status.phase != "Bound":
            issues.append(HealthIssue(
                severity=SEVERITY_WARNING,
                category="PVC",
                resource=pvc.metadata.name,
                namespace=pvc.metadata.namespace,
                message=f"PVC in {pvc.status.phase} state (not Bound)",
                recommendation="Check StorageClass and available PVs: kubectl get pv",
            ))
    return issues


def check_hpa(autoscaling_v1, namespace: Optional[str]) -> List[HealthIssue]:
    issues = []
    try:
        hpas = (
            autoscaling_v1.list_namespaced_horizontal_pod_autoscaler(namespace=namespace).items
            if namespace
            else autoscaling_v1.list_horizontal_pod_autoscaler_for_all_namespaces().items
        )
        for hpa in hpas:
            ns = hpa.metadata.namespace
            name = hpa.metadata.name
            current = hpa.status.current_replicas
            maximum = hpa.spec.max_replicas
            if current == maximum:
                issues.append(HealthIssue(
                    severity=SEVERITY_WARNING,
                    category="HPA",
                    resource=name,
                    namespace=ns,
                    message=f"HPA at max replicas ({current}/{maximum}) — may be capacity-constrained",
                    recommendation="Review max replicas limit or investigate workload spike",
                ))
    except Exception:
        pass
    return issues


def print_report(all_issues: List[HealthIssue], output_path: Optional[str]):
    counts = {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 0, SEVERITY_OK: 0}
    for issue in all_issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1

    print(f"\n{'='*60}")
    print(f"  Kubernetes Cluster Health Report")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  CRITICAL : {counts[SEVERITY_CRITICAL]}")
    print(f"  WARNING  : {counts[SEVERITY_WARNING]}")
    print(f"  OK       : {counts[SEVERITY_OK]}")
    print(f"{'='*60}\n")

    for severity in [SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_OK]:
        group = [i for i in all_issues if i.severity == severity]
        if not group:
            continue
        print(f"--- {severity} ---")
        for issue in group:
            print(f"  [{issue.category}] {issue.namespace}/{issue.resource}")
            print(f"    {issue.message}")
            if issue.recommendation:
                print(f"    > {issue.recommendation}")
            print()

    if output_path:
        with open(output_path, "w") as f:
            json.dump([asdict(i) for i in all_issues], f, indent=2)
        print(f"Report saved: {output_path}")

    return counts[SEVERITY_CRITICAL]


def main():
    parser = argparse.ArgumentParser(description="Kubernetes Cluster Health Checker")
    parser.add_argument("--namespace", help="Limit checks to a namespace")
    parser.add_argument("--output", help="Save JSON report to file")
    args = parser.parse_args()

    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    autoscaling_v1 = client.AutoscalingV1Api()

    all_issues = []
    print("Running checks...")
    all_issues += check_nodes(v1)
    all_issues += check_pods(v1, args.namespace)
    all_issues += check_deployments(apps_v1, args.namespace)
    all_issues += check_pvcs(v1, args.namespace)
    all_issues += check_hpa(autoscaling_v1, args.namespace)

    critical_count = print_report(all_issues, args.output)
    sys.exit(1 if critical_count > 0 else 0)


if __name__ == "__main__":
    main()
