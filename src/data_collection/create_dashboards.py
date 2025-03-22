#!/usr/bin/env python3
import argparse
import json
import os
import requests
import sys
from datetime import datetime

# Default Grafana configuration
DEFAULT_GRAFANA_URL = "http://grafana.monitoring.svc.cluster.local:3000"
DEFAULT_GRAFANA_API_KEY = ""  # Should be provided via command line or environment variable
DEFAULT_DASHBOARD_DIR = "dashboards"

# Dashboard templates for each category of metrics
DASHBOARD_TEMPLATES = {
    "container_runtime": {
        "title": "Container Runtime Metrics",
        "description": "Dashboard for container runtime metrics",
        "panels": [
            {"title": "Container CPU Usage", "query": "container_runtime_cpu_usage", "type": "graph"},
            {"title": "Container Memory Usage", "query": "container_runtime_memory_usage", "type": "graph"},
            {"title": "Container Memory Failures", "query": "container_runtime_memory_failures", "type": "graph"},
            {"title": "Container Processes", "query": "container_runtime_processes", "type": "graph"},
            {"title": "Container Threads", "query": "container_runtime_threads", "type": "graph"},
            {"title": "Container I/O Reads", "query": "container_runtime_io_reads", "type": "graph"},
            {"title": "Container I/O Writes", "query": "container_runtime_io_writes", "type": "graph"}
        ]
    },
    "service": {
        "title": "Service Metrics",
        "description": "Dashboard for service response times and availability metrics",
        "panels": [
            {"title": "Service Request Duration (95th percentile)", "query": "service_request_duration", "type": "graph"},
            {"title": "Service Success Rate", "query": "service_success_rate", "type": "graph"},
            {"title": "Endpoint Response Time (95th percentile)", "query": "endpoint_response_time", "type": "graph"},
            {"title": "Endpoint Availability", "query": "endpoint_availability", "type": "stat"},
            {"title": "Service Error Rate", "query": "service_error_rate", "type": "graph"}
        ]
    },
    "apiserver": {
        "title": "API Server Metrics",
        "description": "Dashboard for Kubernetes API server metrics",
        "panels": [
            {"title": "API Server Request Latency (95th percentile)", "query": "apiserver_request_latency", "type": "graph"},
            {"title": "API Server Request Rate", "query": "apiserver_request_rate", "type": "graph"},
            {"title": "API Server Error Rate", "query": "apiserver_error_rate", "type": "graph"},
            {"title": "API Server Request Terminations", "query": "apiserver_request_terminations", "type": "graph"},
            {"title": "API Server Client Certificate Expiry", "query": "apiserver_client_cert_expiry", "type": "stat"},
            {"title": "Webhook Latency (95th percentile)", "query": "webhook_latency", "type": "graph"}
        ]
    },
    "etcd": {
        "title": "etcd Metrics",
        "description": "Dashboard for etcd database metrics",
        "panels": [
            {"title": "etcd Has Leader", "query": "etcd_has_leader", "type": "stat"},
            {"title": "etcd Leader Changes", "query": "etcd_leader_changes", "type": "graph"},
            {"title": "etcd Proposal Failures", "query": "etcd_proposal_failures", "type": "graph"},
            {"title": "etcd Request Latency (95th percentile)", "query": "etcd_request_latency", "type": "graph"},
            {"title": "etcd Disk Latency (95th percentile)", "query": "etcd_disk_latency", "type": "graph"},
            {"title": "etcd Compaction Duration (95th percentile)", "query": "etcd_compaction_duration", "type": "graph"},
            {"title": "etcd Network Latency (95th percentile)", "query": "etcd_network_latency", "type": "graph"}
        ]
    },
    "loadbalancer": {
        "title": "Load Balancer Metrics",
        "description": "Dashboard for load balancer metrics",
        "panels": [
            {"title": "Load Balancer Request Rate", "query": "lb_request_rate", "type": "graph"},
            {"title": "Load Balancer Response Time (95th percentile)", "query": "lb_response_time", "type": "graph"},
            {"title": "Load Balancer Error Rate", "query": "lb_error_rate", "type": "graph"},
            {"title": "Load Balancer Connections", "query": "lb_connections", "type": "graph"},
            {"title": "Load Balancer SSL Handshake Failures", "query": "lb_ssl_handshake_failures", "type": "graph"}
        ]
    },
    "ingress": {
        "title": "Ingress Controller Metrics",
        "description": "Dashboard for ingress controller metrics",
        "panels": [
            {"title": "Ingress Success Rate", "query": "ingress_success_rate", "type": "graph"},
            {"title": "Ingress Latency (95th percentile)", "query": "ingress_latency", "type": "graph"},
            {"title": "Ingress Request Rate", "query": "ingress_request_rate", "type": "graph"},
            {"title": "Ingress Upstream Latency (95th percentile)", "query": "ingress_upstream_latency", "type": "graph"},
            {"title": "Ingress Socket Errors", "query": "ingress_socket_errors", "type": "graph"}
        ]
    },
    "crd": {
        "title": "Custom Resource Metrics",
        "description": "Dashboard for CRD and custom controller metrics",
        "panels": [
            {"title": "CRD Instance Count", "query": "crd_instance_count", "type": "graph"},
            {"title": "CRD Controller Reconcile Time (95th percentile)", "query": "crd_controller_reconcile_time", "type": "graph"},
            {"title": "CRD Controller Queue Depth", "query": "crd_controller_queue_depth", "type": "graph"},
            {"title": "CRD Controller Work Duration (95th percentile)", "query": "crd_controller_work_duration", "type": "graph"},
            {"title": "CRD Controller Retries", "query": "crd_controller_retries", "type": "graph"}
        ]
    },
    "scheduling": {
        "title": "Pod Scheduling Metrics",
        "description": "Dashboard for pod scheduling metrics",
        "panels": [
            {"title": "Scheduling Attempts", "query": "scheduling_attempts", "type": "graph"},
            {"title": "Scheduling Latency (95th percentile)", "query": "scheduling_latency", "type": "graph"},
            {"title": "Scheduling E2E Latency (95th percentile)", "query": "scheduling_e2e_latency", "type": "graph"},
            {"title": "Pending Pods", "query": "pending_pods", "type": "graph"},
            {"title": "Pod Preemptions", "query": "pod_preemptions", "type": "graph"},
            {"title": "Scheduling Errors", "query": "scheduling_errors", "type": "graph"}
        ]
    },
    "resource_quota": {
        "title": "Resource Quota Metrics",
        "description": "Dashboard for resource quota utilization metrics",
        "panels": [
            {"title": "CPU Quota Usage", "query": "quota_cpu_usage", "type": "graph"},
            {"title": "Memory Quota Usage", "query": "quota_memory_usage", "type": "graph"},
            {"title": "Pods Quota Usage", "query": "quota_pods_usage", "type": "graph"},
            {"title": "CPU Hard Limits", "query": "quota_cpu_hard", "type": "graph"},
            {"title": "Memory Hard Limits", "query": "quota_memory_hard", "type": "graph"},
            {"title": "CPU Used", "query": "quota_cpu_used", "type": "graph"},
            {"title": "Memory Used", "query": "quota_memory_used", "type": "graph"},
            {"title": "Limit Range Defaults", "query": "limit_range_defaults", "type": "table"}
        ]
    }
}

def generate_dashboard_json(template, datasource_name="Prometheus"):
    """Generate a Grafana dashboard JSON based on a template"""
    dashboard = {
        "title": template["title"],
        "description": template["description"],
        "tags": ["kubernetes", "enhanced-metrics"],
        "time": {
            "from": "now-6h",
            "to": "now"
        },
        "refresh": "1m",
        "panels": []
    }
    
    # Generate panels based on template
    panel_id = 1
    y_pos = 0
    
    for panel_template in template["panels"]:
        panel = {
            "id": panel_id,
            "title": panel_template["title"],
            "type": panel_template["type"],
            "gridPos": {
                "h": 8,
                "w": 12,
                "x": (panel_id - 1) % 2 * 12,
                "y": y_pos
            },
            "datasource": {
                "type": "prometheus",
                "uid": "prometheus"
            },
            "targets": [
                {
                    "expr": panel_template["query"],
                    "refId": "A"
                }
            ]
        }
        
        dashboard["panels"].append(panel)
        panel_id += 1
        
        # Adjust y position for next row if needed
        if panel_id % 2 == 1:
            y_pos += 8
    
    # Wrap in the format expected by the Grafana API
    result = {
        "dashboard": dashboard,
        "overwrite": True,
        "message": f"Dashboard updated at {datetime.now().isoformat()}"
    }
    
    return result

def save_dashboard_to_file(dashboard_json, output_dir, name):
    """Save a dashboard JSON to a file"""
    os.makedirs(output_dir, exist_ok=True)
    
    filename = os.path.join(output_dir, f"{name}.json")
    with open(filename, "w") as f:
        json.dump(dashboard_json, f, indent=2)
    
    print(f"Dashboard saved to {filename}")
    return filename

def upload_dashboard_to_grafana(dashboard_json, grafana_url, api_key):
    """Upload a dashboard JSON to Grafana via API"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    response = requests.post(
        f"{grafana_url}/api/dashboards/db",
        headers=headers,
        json=dashboard_json
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"Dashboard uploaded to Grafana: {result.get('url', 'Unknown URL')}")
        return True
    else:
        print(f"Failed to upload dashboard: {response.status_code} - {response.text}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Generate Grafana dashboards for enhanced Kubernetes metrics")
    parser.add_argument("--category", choices=list(DASHBOARD_TEMPLATES.keys()) + ["all"], default="all",
                       help="Category of dashboard to generate")
    parser.add_argument("--output-dir", default=DEFAULT_DASHBOARD_DIR,
                       help="Directory to save dashboard JSON files")
    parser.add_argument("--upload", action="store_true",
                       help="Upload dashboards to Grafana")
    parser.add_argument("--grafana-url", default=DEFAULT_GRAFANA_URL,
                       help="Grafana base URL")
    parser.add_argument("--api-key",
                       help="Grafana API key (or set GRAFANA_API_KEY environment variable)")
    
    args = parser.parse_args()
    
    # Check if we need to upload and have the required credentials
    if args.upload:
        api_key = args.api_key or os.environ.get("GRAFANA_API_KEY") or DEFAULT_GRAFANA_API_KEY
        if not api_key:
            print("Error: Grafana API key required for upload. Use --api-key or set GRAFANA_API_KEY environment variable.")
            return 1
    
    # Determine which categories to generate
    categories = list(DASHBOARD_TEMPLATES.keys()) if args.category == "all" else [args.category]
    
    # Generate and process each dashboard
    for category in categories:
        print(f"Generating dashboard for {category} metrics...")
        template = DASHBOARD_TEMPLATES[category]
        dashboard_json = generate_dashboard_json(template)
        
        # Save to file
        filename = save_dashboard_to_file(dashboard_json, args.output_dir, category)
        
        # Upload if requested
        if args.upload:
            print(f"Uploading {category} dashboard to Grafana...")
            upload_dashboard_to_grafana(dashboard_json, args.grafana_url, api_key)
    
    print(f"Generated {len(categories)} dashboards.")
    return 0

if __name__ == "__main__":
    sys.exit(main()) 