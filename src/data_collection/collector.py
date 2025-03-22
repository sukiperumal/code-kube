import argparse
import requests
import pandas as pd
import numpy as np
import os
import time
import json
from datetime import datetime, timedelta
import kubernetes.client
import kubernetes.config
from prometheus_api_client import PrometheusConnect
from .enhanced_metrics import EnhancedMetricsCollector
import csv

class KubernetesMetricsCollector:
    """Class to collect Kubernetes metrics from Prometheus."""
    
    METRICS_CATEGORIES = [
        "container_runtime",
        "service",
        "apiserver",
        "etcd", 
        "loadbalancer",
        "ingress",
        "crd",
        "scheduling",
        "resource_quota",
        "node",
        "pod"
    ]
    
    def __init__(self, prometheus_url="http://prometheus-server.monitoring.svc.cluster.local:9090"):
        """Initialize the collector with Prometheus connection."""
        self.prometheus_url = prometheus_url
        self.prometheus_connector = self._init_prometheus_connector()
        self.enhanced_metrics_collector = EnhancedMetricsCollector(prometheus_url=prometheus_url)
        
        # Initialize Kubernetes client
        kubernetes.config.load_kube_config()
        self.k8s_client = kubernetes.client.CoreV1Api()
        self.custom_api = kubernetes.client.CustomObjectsApi()
        
        # Create output directory if it doesn't exist
        os.makedirs("data/raw", exist_ok=True)
        os.makedirs("data/processed", exist_ok=True)
    
    def query_prometheus(self, query, start_time=None, end_time=None, step="15s"):
        """Query Prometheus for the given PromQL query over the specified time range."""
        if start_time is None:
            start_time = datetime.now() - timedelta(minutes=30)
        if end_time is None:
            end_time = datetime.now()
            
        result = self.prometheus_connector.custom_query_range(
            query=query,
            start_time=start_time,
            end_time=end_time,
            step=step
        )
        return result
    
    def collect_node_metrics(self, start_time=None, end_time=None, step="15s"):
        """Collect node-level metrics (CPU, memory, disk, network)."""
        metrics = {
            "node_cpu_usage": "sum by (node) (rate(node_cpu_seconds_total{mode!='idle'}[5m]))",
            "node_memory_usage": "sum by (node) (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)",
            "node_memory_total": "sum by (node) (node_memory_MemTotal_bytes)",
            "node_disk_usage": "sum by (node) (node_filesystem_size_bytes - node_filesystem_free_bytes)",
            "node_disk_total": "sum by (node) (node_filesystem_size_bytes)",
            "node_network_receive_bytes": "sum by (node) (rate(node_network_receive_bytes_total[5m]))",
            "node_network_transmit_bytes": "sum by (node) (rate(node_network_transmit_bytes_total[5m]))"
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_pod_metrics(self, start_time=None, end_time=None, step="15s", namespaces=None):
        """Collect pod-level metrics (CPU, memory, restarts, status)."""
        if namespaces is None:
            namespaces = ["default", "kube-system"]
            
        namespace_selector = '|'.join(namespaces)
        
        metrics = {
            "pod_cpu_usage": f'sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{{namespace=~"{namespace_selector}"}}[5m]))',
            "pod_memory_usage": f'sum by (pod, namespace) (container_memory_usage_bytes{{namespace=~"{namespace_selector}"}})',
            "pod_network_receive": f'sum by (pod, namespace) (rate(container_network_receive_bytes_total{{namespace=~"{namespace_selector}"}}[5m]))',
            "pod_network_transmit": f'sum by (pod, namespace) (rate(container_network_transmit_bytes_total{{namespace=~"{namespace_selector}"}}[5m]))',
            "pod_restarts": f'sum by (pod, namespace) (kube_pod_container_status_restarts_total{{namespace=~"{namespace_selector}"}})',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_events(self, namespaces=None):
        """Collect Kubernetes events."""
        if namespaces is None:
            namespaces = ["default", "kube-system"]
        
        events = []
        for namespace in namespaces:
            try:
                ns_events = self.k8s_client.list_namespaced_event(namespace)
                for event in ns_events.items:
                    events.append({
                        "namespace": namespace,
                        "name": event.metadata.name,
                        "reason": event.reason,
                        "message": event.message,
                        "count": event.count,
                        "type": event.type,
                        "first_timestamp": event.first_timestamp.isoformat() if event.first_timestamp else None,
                        "last_timestamp": event.last_timestamp.isoformat() if event.last_timestamp else None,
                        "involved_object": {
                            "kind": event.involved_object.kind,
                            "name": event.involved_object.name
                        }
                    })
            except kubernetes.client.rest.ApiException as e:
                print(f"Error collecting events from namespace {namespace}: {e}")
        
        return events
    
    def collect_metrics(self, duration_minutes=30, step="15s", namespaces=None, cluster_issue_type=None, categories=None):
        """
        Collect all metrics for the specified duration.
        
        Args:
            duration_minutes (int): Duration in minutes to collect metrics for
            step (str): Step interval for Prometheus queries
            namespaces (list): List of namespaces to collect metrics for
            cluster_issue_type (str): Type of cluster issue being simulated (if any)
            categories (list): List of metric categories to collect (defaults to all)
            
        Returns:
            dict: Dictionary of collected metrics
        """
        if namespaces is None:
            namespaces = ["default", "kube-system"]
            
        # If no categories specified, collect all
        if categories is None:
            categories = self.METRICS_CATEGORIES
            
        print(f"Collecting metrics for categories: {categories}")
            
        # Calculate time range
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=duration_minutes)
        
        # Initialize metrics dictionary
        metrics = {
            "metadata": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_minutes": duration_minutes,
                "cluster_issue_type": cluster_issue_type,
                "namespaces": namespaces,
                "categories": categories
            }
        }
        
        # Standard collections
        if "node" in categories:
            print("Collecting node metrics...")
            metrics["node"] = self.collect_node_metrics(start_time, end_time, step)
            
        if "pod" in categories:
            print("Collecting pod metrics...")
            metrics["pod"] = self.collect_pod_metrics(start_time, end_time, step, namespaces)
        
        # Enhanced collections
        if "container_runtime" in categories:
            print("Collecting container runtime metrics...")
            metrics["container_runtime"] = self.enhanced_metrics_collector.collect_container_runtime_metrics(
                start_time, end_time, step, namespaces
            )
            
        if "service" in categories:
            print("Collecting service metrics...")
            metrics["service"] = self.enhanced_metrics_collector.collect_service_metrics(
                start_time, end_time, step, namespaces
            )
            
        if "apiserver" in categories:
            print("Collecting API server metrics...")
            metrics["apiserver"] = self.enhanced_metrics_collector.collect_apiserver_metrics(
                start_time, end_time, step
            )
            
        if "etcd" in categories:
            print("Collecting etcd metrics...")
            metrics["etcd"] = self.enhanced_metrics_collector.collect_etcd_metrics(
                start_time, end_time, step
            )
            
        if "loadbalancer" in categories:
            print("Collecting load balancer metrics...")
            metrics["loadbalancer"] = self.enhanced_metrics_collector.collect_loadbalancer_metrics(
                start_time, end_time, step
            )
            
        if "ingress" in categories:
            print("Collecting ingress metrics...")
            metrics["ingress"] = self.enhanced_metrics_collector.collect_ingress_metrics(
                start_time, end_time, step
            )
            
        if "crd" in categories:
            print("Collecting CRD metrics...")
            metrics["crd"] = self.enhanced_metrics_collector.collect_crd_metrics(
                start_time, end_time, step
            )
            
        if "scheduling" in categories:
            print("Collecting scheduling metrics...")
            metrics["scheduling"] = self.enhanced_metrics_collector.collect_scheduling_metrics(
                start_time, end_time, step
            )
            
        if "resource_quota" in categories:
            print("Collecting resource quota metrics...")
            metrics["resource_quota"] = self.enhanced_metrics_collector.collect_resource_quota_metrics(
                start_time, end_time, step, namespaces
            )
        
        # Collect events
        print("Collecting events...")
        metrics["events"] = self.collect_events(namespaces)
        
        # Save raw metrics to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"data/raw/metrics_{timestamp}.json"
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        with open(output_file, "w") as f:
            json.dump(metrics, f, indent=2, default=str)
            
        print(f"Raw metrics saved to {output_file}")
        
        # Process metrics to tabular format
        processed_file = self.process_metrics(output_file)
        
        return {
            "raw_file": output_file,
            "processed_file": processed_file,
            "metrics": metrics
        }
    
    def process_metrics(self, raw_file):
        """Process raw metrics JSON file to tabular format CSV."""
        print(f"Processing metrics from {raw_file}...")
        
        with open(raw_file, "r") as f:
            metrics = json.load(f)
        
        # Extract metadata
        metadata = metrics.get("metadata", {})
        start_time = metadata.get("start_time", "")
        end_time = metadata.get("end_time", "")
        duration_minutes = metadata.get("duration_minutes", 0)
        cluster_issue_type = metadata.get("cluster_issue_type", "")
        
        # Generate output file name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"data/processed/metrics_{timestamp}.csv"
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # Process metrics into tabular format
        rows = []
        
        # Process time series data
        node_metrics = metrics.get("node", {})
        pod_metrics = metrics.get("pod", {})
        
        # Get timestamps from any available time series
        timestamps = []
        for metric_name, metric_data in node_metrics.items():
            for node, time_series in metric_data.items():
                timestamps = [entry[0] for entry in time_series]
                break
            if timestamps:
                break
                
        if not timestamps:
            # Check pod metrics if node metrics didn't have timestamps
            for metric_name, metric_data in pod_metrics.items():
                for pod_key, time_series in metric_data.items():
                    timestamps = [entry[0] for entry in time_series]
                    break
                if timestamps:
                    break
        
        # Create row for each timestamp
        for timestamp_index, timestamp in enumerate(timestamps):
            dt = datetime.fromtimestamp(timestamp)
            
            row = {
                "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # Add node metrics
            for metric_name, metric_data in node_metrics.items():
                for node, time_series in metric_data.items():
                    if timestamp_index < len(time_series):
                        value = time_series[timestamp_index][1]
                        row[f"{metric_name}"] = value
                        
            # Add pod metrics
            for metric_name, metric_data in pod_metrics.items():
                for pod_key, time_series in metric_data.items():
                    pod_namespace, pod_name = pod_key.split("|") if "|" in pod_key else (pod_key, "")
                    if timestamp_index < len(time_series):
                        value = time_series[timestamp_index][1]
                        row[f"{metric_name}_{pod_namespace}_{pod_name}"] = value
                        
            # Add enhanced metrics for each category
            for category in self.METRICS_CATEGORIES:
                if category not in ["node", "pod"] and category in metrics:
                    category_metrics = metrics.get(category, {})
                    for metric_name, metric_data in category_metrics.items():
                        if isinstance(metric_data, dict):
                            for item_key, time_series in metric_data.items():
                                if timestamp_index < len(time_series):
                                    value = time_series[timestamp_index][1]
                                    row[f"{category}_{metric_name}_{item_key}"] = value
                        elif isinstance(metric_data, list) and metric_data and timestamp_index < len(metric_data):
                            value = metric_data[timestamp_index][1]
                            row[f"{category}_{metric_name}"] = value
            
            # Add cluster issue type
            row["issue_type"] = cluster_issue_type
            
            # Process events associated with this timestamp
            self.process_events(metrics.get("events", {}), timestamp_index)
            
            # Add the row
            rows.append(row)
            
        # Write to CSV
        if rows:
            headers = list(rows[0].keys())
            
            with open(output_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
                
            print(f"Processed metrics saved to {output_file}")
        else:
            print("No data to write!")
            
        return output_file
    
    def process_events(self, events, index):
        """Process events into a dataframe with event types as columns."""
        # Create a dataframe with timestamps as index
        event_df = pd.DataFrame(index=index)
        
        # Create columns for common event types
        event_types = ["Normal", "Warning", "Error"]
        for event_type in event_types:
            event_df[f"event_{event_type.lower()}_count"] = 0
        
        # Additional columns for specific events
        event_reasons = ["Killing", "Created", "Started", "BackOff", "Failed", "Unhealthy"]
        for reason in event_reasons:
            event_df[f"event_reason_{reason.lower()}"] = 0
        
        # Process each event
        for event in events:
            event_type = event.get("type", "Unknown")
            reason = event.get("reason", "Unknown")
            
            # Find the closest timestamp in our index
            if event.get("last_timestamp"):
                # Convert event timestamp to match index timezone awareness
                event_time = datetime.fromisoformat(event["last_timestamp"].replace("Z", "+00:00"))
                event_time_ts = pd.Timestamp(event_time)
                
                # If index has timezone info and event_time doesn't, localize event_time
                if index.dtype.kind == 'M' and hasattr(index, 'tz') and index.tz is not None:
                    if event_time_ts.tz is None:
                        event_time_ts = event_time_ts.tz_localize(index.tz)
                # If index has no timezone and event_time does, convert event_time to naive
                elif event_time_ts.tz is not None:
                    event_time_ts = event_time_ts.tz_localize(None)
                
                # Find the nearest timestamp in our index
                if not index.empty:
                    nearest_idx = index[np.abs(index - event_time_ts).argmin()]
                    
                    # Increment the event type counter
                    if event_type in event_types:
                        event_df.at[nearest_idx, f"event_{event_type.lower()}_count"] += 1
                    
                    # Increment the event reason counter
                    if reason in event_reasons:
                        event_df.at[nearest_idx, f"event_reason_{reason.lower()}"] = 1
        
        return event_df

def main():
    parser = argparse.ArgumentParser(description="Collect metrics from a Kubernetes cluster")
    parser.add_argument("--prometheus-url", default="http://prometheus-server.monitoring.svc.cluster.local:9090", 
                       help="URL of the Prometheus server")
    parser.add_argument("--duration", type=int, default=30, 
                       help="Duration in minutes to collect metrics for")
    parser.add_argument("--step", default="15s", 
                       help="Step interval for Prometheus queries")
    parser.add_argument("--namespaces", nargs="+", default=["default", "kube-system"],
                       help="Namespaces to collect metrics from")
    parser.add_argument("--process", action="store_true", 
                       help="Process the collected metrics after collection")
    parser.add_argument("--output-dir", default="data",
                       help="Directory to save output files to")
    parser.add_argument("--cluster-issue-type", 
                       help="Type of cluster issue being simulated")
    parser.add_argument("--check-connection-only", action="store_true",
                       help="Only check connection to Prometheus and exit")
    
    args = parser.parse_args()
    
    # Create the collector
    collector = KubernetesMetricsCollector(prometheus_url=args.prometheus_url)
    
    # Check connection if requested
    if args.check_connection_only:
        try:
            response = requests.get(f"{args.prometheus_url}/api/v1/status/config", timeout=10)
            response.raise_for_status()
            print(f"✅ Successfully connected to Prometheus at {args.prometheus_url}")
            return 0
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to connect to Prometheus at {args.prometheus_url}")
            print(f"Error: {e}")
            return 1
    
    # Collect metrics
    metrics_dict = collector.collect_metrics(
        duration_minutes=args.duration,
        step=args.step,
        namespaces=args.namespaces,
        cluster_issue_type=args.cluster_issue_type
    )
    
    # Process metrics if requested
    if args.process and metrics_dict["processed_file"]:
        print(f"Data collection and processing complete.")
        return 0
    
    return 0

if __name__ == "__main__":
    main() 