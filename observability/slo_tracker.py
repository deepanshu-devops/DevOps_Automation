"""
observability/slo_tracker.py
------------------------------
Queries Prometheus to calculate SLI (Service Level Indicator) metrics,
compute SLO compliance, and report remaining error budget.

Directly tied to: Deepanshu's resume — "Defined SLIs and SLOs and enforced
error budgets across services" and MTTR improvement from 40 → 30 minutes.

Metrics tracked:
  - Availability SLO (target: 99.9% / 99.95%)
  - Latency SLO (target: p99 < 500ms)
  - Error rate SLO
  - Error budget burn rate alert

Usage:
    python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api
    python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api --window 7d
    python observability/slo_tracker.py --prometheus http://prometheus:9090 --all-services
"""

import argparse
import json
from datetime import datetime
from typing import Optional
import urllib.request
import urllib.parse


class PrometheusClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def query(self, promql: str) -> Optional[float]:
        url = f"{self.base_url}/api/v1/query?" + urllib.parse.urlencode({"query": promql})
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            results = data.get("data", {}).get("result", [])
            if results:
                return float(results[0]["value"][1])
        except Exception as e:
            print(f"  Prometheus query failed: {e}")
        return None

    def query_range(self, promql: str, window: str) -> Optional[float]:
        return self.query(f"{promql}[{window}]")


class SLOTracker:
    def __init__(self, prom: PrometheusClient, service: str, window: str):
        self.prom = prom
        self.service = service
        self.window = window

    def availability_sli(self) -> Optional[float]:
        """Ratio of successful requests to total requests."""
        query = (
            f'sum(rate(http_requests_total{{service="{self.service}", '
            f'status!~"5.."}}[{self.window}])) / '
            f'sum(rate(http_requests_total{{service="{self.service}"}}[{self.window}]))'
        )
        val = self.prom.query(query)
        return round(val * 100, 4) if val is not None else None

    def latency_p99_ms(self) -> Optional[float]:
        """99th percentile latency in milliseconds."""
        query = (
            f'histogram_quantile(0.99, sum(rate('
            f'http_request_duration_seconds_bucket{{service="{self.service}"}}[{self.window}])) '
            f'by (le)) * 1000'
        )
        val = self.prom.query(query)
        return round(val, 1) if val is not None else None

    def error_rate(self) -> Optional[float]:
        """Error rate as a percentage."""
        query = (
            f'sum(rate(http_requests_total{{service="{self.service}", status=~"5.."}}[{self.window}])) / '
            f'sum(rate(http_requests_total{{service="{self.service}"}}[{self.window}])) * 100'
        )
        val = self.prom.query(query)
        return round(val, 4) if val is not None else None

    def error_budget_remaining(self, slo_target: float = 99.9) -> Optional[float]:
        """
        Error budget = allowed downtime minutes in the window.
        Returns percentage of budget remaining.
        """
        avail = self.availability_sli()
        if avail is None:
            return None
        window_minutes = self._window_to_minutes()
        allowed_downtime = window_minutes * (1 - slo_target / 100)
        actual_downtime = window_minutes * (1 - avail / 100)
        budget_used = actual_downtime / allowed_downtime * 100 if allowed_downtime > 0 else 100
        return round(max(0, 100 - budget_used), 2)

    def _window_to_minutes(self) -> float:
        w = self.window
        if w.endswith("d"):
            return float(w[:-1]) * 1440
        elif w.endswith("h"):
            return float(w[:-1]) * 60
        elif w.endswith("m"):
            return float(w[:-1])
        return 43200  # default 30 days


def format_status(value, threshold_good, threshold_warn, higher_is_better=True) -> str:
    if value is None:
        return "N/A (no data)"
    if higher_is_better:
        if value >= threshold_good:
            return f"{value} [OK]"
        elif value >= threshold_warn:
            return f"{value} [WARNING]"
        else:
            return f"{value} [CRITICAL]"
    else:
        if value <= threshold_good:
            return f"{value} [OK]"
        elif value <= threshold_warn:
            return f"{value} [WARNING]"
        else:
            return f"{value} [CRITICAL]"


def run_report(prom: PrometheusClient, service: str, window: str, slo_target: float):
    tracker = SLOTracker(prom, service, window)
    avail = tracker.availability_sli()
    p99 = tracker.latency_p99_ms()
    error_rate = tracker.error_rate()
    budget = tracker.error_budget_remaining(slo_target)

    print(f"\n  Service  : {service}")
    print(f"  Window   : {window}")
    print(f"  SLO      : {slo_target}% availability")
    print(f"  {'─'*45}")
    print(f"  Availability  : {format_status(avail, slo_target, slo_target - 0.5)}%")
    print(f"  p99 Latency   : {format_status(p99, 500, 1000, higher_is_better=False)} ms")
    print(f"  Error rate    : {format_status(error_rate, 0.1, 1.0, higher_is_better=False)}%")
    print(f"  Error budget  : {format_status(budget, 25, 10)}% remaining")

    if budget is not None and budget < 10:
        print(f"\n  ALERT: Error budget below 10% — consider feature freeze")
    elif budget is not None and budget < 25:
        print(f"\n  WARNING: Error budget below 25% — review recent deployments")


def main():
    parser = argparse.ArgumentParser(description="SLO Tracker — Prometheus-based")
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--service", help="Service name label in Prometheus metrics")
    parser.add_argument("--window", default="30d", help="Query window e.g. 7d, 24h, 30d")
    parser.add_argument("--slo-target", type=float, default=99.9)
    parser.add_argument("--all-services", action="store_true")
    args = parser.parse_args()

    prom = PrometheusClient(args.prometheus)
    print(f"\nSLO Tracker — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}")

    if args.all_services:
        # Discover services from Prometheus labels
        result = prom.query('group by (service) (http_requests_total)')
        services = []
        if result:
            services = [r.get("metric", {}).get("service") for r in result if isinstance(r, dict)]
        services = [s for s in services if s]
        if not services:
            print("No services found. Try --service <name> directly.")
            return
        for svc in services:
            run_report(prom, svc, args.window, args.slo_target)
    elif args.service:
        run_report(prom, args.service, args.window, args.slo_target)
    else:
        print("Provide --service <name> or --all-services")


if __name__ == "__main__":
    main()
