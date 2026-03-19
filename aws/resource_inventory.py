"""
aws/resource_inventory.py
--------------------------
Generates a complete inventory of all AWS resources across one or multiple
regions and exports to CSV, JSON, or prints a summary table.

Covers: EC2 instances, EBS volumes, S3 buckets, RDS instances, Lambda
functions, VPCs, Subnets, Security Groups, IAM users/roles, Route 53
hosted zones, Load Balancers, Auto Scaling Groups, CloudWatch Alarms.

Directly relevant to: Deepanshu's multi-service AWS expertise (15+ services)
and cloud migration work for Bell Canada — you need a full inventory before
you can migrate or optimise anything.

Usage:
    python aws/resource_inventory.py --region ap-south-1
    python aws/resource_inventory.py --region ap-south-1 --output inventory.csv
    python aws/resource_inventory.py --region ap-south-1 --output inventory.json --format json
    python aws/resource_inventory.py --all-regions --output full_inventory.csv
"""

import argparse
import boto3
import csv
import json
import sys
from datetime import datetime, timezone
from typing import List


RESOURCE_TYPES = [
    "ec2_instances", "ebs_volumes", "s3_buckets", "rds_instances",
    "lambda_functions", "vpcs", "subnets", "security_groups",
    "iam_users", "iam_roles", "load_balancers", "auto_scaling_groups",
    "cloudwatch_alarms", "route53_zones",
]


def collect_ec2_instances(region: str) -> List[dict]:
    ec2 = boto3.client("ec2", region_name=region)
    resources = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                name = next(
                    (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), ""
                )
                resources.append({
                    "type": "EC2 Instance",
                    "id": inst["InstanceId"],
                    "name": name,
                    "region": region,
                    "state": inst["State"]["Name"],
                    "detail": f"{inst['InstanceType']} | {inst.get('PrivateIpAddress', '')}",
                    "created": str(inst.get("LaunchTime", "")),
                })
    return resources


def collect_ebs_volumes(region: str) -> List[dict]:
    ec2 = boto3.client("ec2", region_name=region)
    resources = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate():
        for vol in page["Volumes"]:
            name = next(
                (t["Value"] for t in vol.get("Tags", []) if t["Key"] == "Name"), ""
            )
            attachments = vol.get("Attachments", [])
            attached_to = attachments[0]["InstanceId"] if attachments else "unattached"
            resources.append({
                "type": "EBS Volume",
                "id": vol["VolumeId"],
                "name": name,
                "region": region,
                "state": vol["State"],
                "detail": f"{vol['VolumeType']} | {vol['Size']}GB | {attached_to}",
                "created": str(vol.get("CreateTime", "")),
            })
    return resources


def collect_s3_buckets() -> List[dict]:
    s3 = boto3.client("s3")
    resources = []
    response = s3.list_buckets()
    for bucket in response.get("Buckets", []):
        try:
            location = s3.get_bucket_location(Bucket=bucket["Name"])
            region = location.get("LocationConstraint") or "us-east-1"
        except Exception:
            region = "unknown"
        resources.append({
            "type": "S3 Bucket",
            "id": bucket["Name"],
            "name": bucket["Name"],
            "region": region,
            "state": "active",
            "detail": "S3 Bucket",
            "created": str(bucket.get("CreationDate", "")),
        })
    return resources


def collect_rds_instances(region: str) -> List[dict]:
    rds = boto3.client("rds", region_name=region)
    resources = []
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for db in page["DBInstances"]:
            resources.append({
                "type": "RDS Instance",
                "id": db["DBInstanceIdentifier"],
                "name": db["DBInstanceIdentifier"],
                "region": region,
                "state": db["DBInstanceStatus"],
                "detail": f"{db['DBInstanceClass']} | {db['Engine']} {db.get('EngineVersion','')} | {db.get('MultiAZ', False) and 'Multi-AZ' or 'Single-AZ'}",
                "created": str(db.get("InstanceCreateTime", "")),
            })
    return resources


def collect_lambda_functions(region: str) -> List[dict]:
    lam = boto3.client("lambda", region_name=region)
    resources = []
    paginator = lam.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            resources.append({
                "type": "Lambda Function",
                "id": fn["FunctionArn"],
                "name": fn["FunctionName"],
                "region": region,
                "state": fn.get("State", "Active"),
                "detail": f"{fn['Runtime']} | {fn['MemorySize']}MB | timeout {fn['Timeout']}s",
                "created": fn.get("LastModified", ""),
            })
    return resources


def collect_vpcs(region: str) -> List[dict]:
    ec2 = boto3.client("ec2", region_name=region)
    resources = []
    for vpc in ec2.describe_vpcs()["Vpcs"]:
        name = next(
            (t["Value"] for t in vpc.get("Tags", []) if t["Key"] == "Name"), ""
        )
        resources.append({
            "type": "VPC",
            "id": vpc["VpcId"],
            "name": name,
            "region": region,
            "state": vpc["State"],
            "detail": f"CIDR: {vpc['CidrBlock']} | {'Default' if vpc['IsDefault'] else 'Custom'}",
            "created": "",
        })
    return resources


def collect_subnets(region: str) -> List[dict]:
    ec2 = boto3.client("ec2", region_name=region)
    resources = []
    paginator = ec2.get_paginator("describe_subnets")
    for page in paginator.paginate():
        for subnet in page["Subnets"]:
            name = next(
                (t["Value"] for t in subnet.get("Tags", []) if t["Key"] == "Name"), ""
            )
            resources.append({
                "type": "Subnet",
                "id": subnet["SubnetId"],
                "name": name,
                "region": region,
                "state": subnet["State"],
                "detail": f"VPC: {subnet['VpcId']} | CIDR: {subnet['CidrBlock']} | AZ: {subnet['AvailabilityZone']}",
                "created": "",
            })
    return resources


def collect_security_groups(region: str) -> List[dict]:
    ec2 = boto3.client("ec2", region_name=region)
    resources = []
    paginator = ec2.get_paginator("describe_security_groups")
    for page in paginator.paginate():
        for sg in page["SecurityGroups"]:
            resources.append({
                "type": "Security Group",
                "id": sg["GroupId"],
                "name": sg["GroupName"],
                "region": region,
                "state": "active",
                "detail": f"VPC: {sg.get('VpcId', 'EC2-Classic')} | {sg['Description'][:60]}",
                "created": "",
            })
    return resources


def collect_iam_users() -> List[dict]:
    iam = boto3.client("iam")
    resources = []
    paginator = iam.get_paginator("list_users")
    for page in paginator.paginate():
        for user in page["Users"]:
            resources.append({
                "type": "IAM User",
                "id": user["UserId"],
                "name": user["UserName"],
                "region": "global",
                "state": "active",
                "detail": f"ARN: {user['Arn']}",
                "created": str(user.get("CreateDate", "")),
            })
    return resources


def collect_iam_roles() -> List[dict]:
    iam = boto3.client("iam")
    resources = []
    paginator = iam.get_paginator("list_roles")
    for page in paginator.paginate():
        for role in page["Roles"]:
            resources.append({
                "type": "IAM Role",
                "id": role["RoleId"],
                "name": role["RoleName"],
                "region": "global",
                "state": "active",
                "detail": f"ARN: {role['Arn']}",
                "created": str(role.get("CreateDate", "")),
            })
    return resources


def collect_load_balancers(region: str) -> List[dict]:
    elb = boto3.client("elbv2", region_name=region)
    resources = []
    paginator = elb.get_paginator("describe_load_balancers")
    for page in paginator.paginate():
        for lb in page["LoadBalancers"]:
            resources.append({
                "type": "Load Balancer",
                "id": lb["LoadBalancerArn"].split("/")[-1],
                "name": lb["LoadBalancerName"],
                "region": region,
                "state": lb["State"]["Code"],
                "detail": f"{lb['Type'].upper()} | {lb['Scheme']} | DNS: {lb['DNSName'][:50]}",
                "created": str(lb.get("CreatedTime", "")),
            })
    return resources


def collect_auto_scaling_groups(region: str) -> List[dict]:
    asg = boto3.client("autoscaling", region_name=region)
    resources = []
    paginator = asg.get_paginator("describe_auto_scaling_groups")
    for page in paginator.paginate():
        for group in page["AutoScalingGroups"]:
            resources.append({
                "type": "Auto Scaling Group",
                "id": group["AutoScalingGroupName"],
                "name": group["AutoScalingGroupName"],
                "region": region,
                "state": "active",
                "detail": f"Min: {group['MinSize']} | Desired: {group['DesiredCapacity']} | Max: {group['MaxSize']} | Running: {len(group['Instances'])}",
                "created": str(group.get("CreatedTime", "")),
            })
    return resources


def collect_cloudwatch_alarms(region: str) -> List[dict]:
    cw = boto3.client("cloudwatch", region_name=region)
    resources = []
    paginator = cw.get_paginator("describe_alarms")
    for page in paginator.paginate():
        for alarm in page["MetricAlarms"]:
            resources.append({
                "type": "CloudWatch Alarm",
                "id": alarm["AlarmArn"].split(":")[-1],
                "name": alarm["AlarmName"],
                "region": region,
                "state": alarm["StateValue"],
                "detail": f"{alarm['MetricName']} {alarm['ComparisonOperator']} {alarm['Threshold']}",
                "created": str(alarm.get("AlarmConfigurationUpdatedTimestamp", "")),
            })
    return resources


def collect_route53_zones() -> List[dict]:
    r53 = boto3.client("route53")
    resources = []
    paginator = r53.get_paginator("list_hosted_zones")
    for page in paginator.paginate():
        for zone in page["HostedZones"]:
            resources.append({
                "type": "Route 53 Hosted Zone",
                "id": zone["Id"].split("/")[-1],
                "name": zone["Name"],
                "region": "global",
                "state": "active",
                "detail": f"{'Private' if zone['Config']['PrivateZone'] else 'Public'} | Records: {zone['ResourceRecordSetCount']}",
                "created": "",
            })
    return resources


def collect_all(region: str) -> List[dict]:
    all_resources = []
    collectors = [
        ("EC2 instances",       lambda: collect_ec2_instances(region)),
        ("EBS volumes",         lambda: collect_ebs_volumes(region)),
        ("S3 buckets",          lambda: collect_s3_buckets()),
        ("RDS instances",       lambda: collect_rds_instances(region)),
        ("Lambda functions",    lambda: collect_lambda_functions(region)),
        ("VPCs",                lambda: collect_vpcs(region)),
        ("Subnets",             lambda: collect_subnets(region)),
        ("Security groups",     lambda: collect_security_groups(region)),
        ("IAM users",           lambda: collect_iam_users()),
        ("IAM roles",           lambda: collect_iam_roles()),
        ("Load balancers",      lambda: collect_load_balancers(region)),
        ("Auto Scaling Groups", lambda: collect_auto_scaling_groups(region)),
        ("CloudWatch alarms",   lambda: collect_cloudwatch_alarms(region)),
        ("Route 53 zones",      lambda: collect_route53_zones()),
    ]
    for label, fn in collectors:
        try:
            items = fn()
            all_resources.extend(items)
            print(f"  {label:<28}: {len(items)}")
        except Exception as e:
            print(f"  {label:<28}: ERROR — {e}")
    return all_resources


def get_all_regions() -> List[str]:
    ec2 = boto3.client("ec2", region_name="us-east-1")
    return [
        r["RegionName"]
        for r in ec2.describe_regions(Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}])["Regions"]
    ]


def save_csv(resources: List[dict], path: str):
    if not resources:
        print("No resources to save.")
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["type", "id", "name", "region", "state", "detail", "created"])
        writer.writeheader()
        writer.writerows(resources)
    print(f"\nInventory saved to: {path} ({len(resources)} resources)")


def save_json(resources: List[dict], path: str):
    with open(path, "w") as f:
        json.dump(resources, f, indent=2, default=str)
    print(f"\nInventory saved to: {path} ({len(resources)} resources)")


def print_summary(resources: List[dict]):
    from collections import Counter
    counts = Counter(r["type"] for r in resources)
    print(f"\n{'='*55}")
    print(f"  AWS Resource Inventory Summary")
    print(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Total resources : {len(resources)}")
    print(f"{'='*55}")
    for rtype, count in sorted(counts.items()):
        print(f"  {rtype:<35}: {count}")


def main():
    parser = argparse.ArgumentParser(description="AWS Full Resource Inventory")
    parser.add_argument("--region", default="ap-south-1", help="AWS region to scan")
    parser.add_argument("--all-regions", action="store_true", help="Scan all available regions")
    parser.add_argument("--output", help="Output file path (.csv or .json)")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    args = parser.parse_args()

    regions = get_all_regions() if args.all_regions else [args.region]
    print(f"\nAWS Resource Inventory")
    print(f"{'='*55}")
    print(f"Regions : {', '.join(regions)}\n")

    all_resources = []
    for region in regions:
        print(f"Scanning {region}...")
        all_resources.extend(collect_all(region))

    print_summary(all_resources)

    if args.output:
        if args.format == "json" or args.output.endswith(".json"):
            save_json(all_resources, args.output)
        else:
            save_csv(all_resources, args.output)


if __name__ == "__main__":
    main()
