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

class KubernetesMetricsCollector:
    """Collect various metrics from a Kubernetes cluster using the Prometheus API."""
    
    def __init__(self, prometheus_url="http://prometheus-server.monitoring.svc.cluster.local:9090"):
        """Initialize the collector with the Prometheus URL."""
        self.prometheus_url = prometheus_url
        self.prom = PrometheusConnect(url=prometheus_url, disable_ssl=True)
        
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
            
        result = self.prom.custom_query_range(
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
    
    def collect_metrics(self, duration_minutes=30, step="15s", namespaces=None, cluster_issue_type=None):
        """Collect all metrics and events for the specified duration and save to file."""
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=duration_minutes)
        
        # Collect metrics
        node_metrics = self.collect_node_metrics(start_time, end_time, step)
        pod_metrics = self.collect_pod_metrics(start_time, end_time, step, namespaces)
        events = self.collect_events(namespaces)
        
        # Combine data
        data = {
            "metadata": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_minutes": duration_minutes,
                "step": step,
                "namespaces": namespaces,
                "cluster_issue_type": cluster_issue_type  # Store the issue type in metadata
            },
            "node_metrics": node_metrics,
            "pod_metrics": pod_metrics,
            "events": events
        }
        
        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        issue_suffix = f"_{cluster_issue_type}" if cluster_issue_type else ""
        filename = f"data/raw/metrics_{timestamp}{issue_suffix}.json"
        with open(filename, "w") as f:
            json.dump(data, f)
        
        print(f"Saved metrics to {filename}")
        return filename
    
    def process_metrics(self, raw_file):
        """Process the raw metrics into a tabular format suitable for ML."""
        with open(raw_file, "r") as f:
            data = json.load(f)
        
        # Extract metadata
        metadata = data["metadata"]
        cluster_issue_type = metadata.get("cluster_issue_type", "none")
        
        # Combine all metrics into a single dataframe
        dfs = []
        
        # Process node metrics
        for metric_name, metric_data in data["node_metrics"].items():
            for time_series in metric_data:
                metric_df = pd.DataFrame({
                    "timestamp": [datetime.fromtimestamp(x[0]) for x in time_series["values"]],
                    f"{metric_name}_{time_series['metric'].get('node', 'unknown')}": [float(x[1]) for x in time_series["values"]]
                })
                dfs.append(metric_df.set_index("timestamp"))
        
        # Process pod metrics
        for metric_name, metric_data in data["pod_metrics"].items():
            for time_series in metric_data:
                pod_name = time_series["metric"].get("pod", "unknown")
                namespace = time_series["metric"].get("namespace", "unknown")
                column_name = f"{metric_name}_{namespace}_{pod_name}"
                
                metric_df = pd.DataFrame({
                    "timestamp": [datetime.fromtimestamp(x[0]) for x in time_series["values"]],
                    column_name: [float(x[1]) for x in time_series["values"]]
                })
                dfs.append(metric_df.set_index("timestamp"))
        
        # Combine all dataframes
        if dfs:
            combined_df = pd.concat(dfs, axis=1)
            # Fill NaN values - replacing deprecated methods
            combined_df = combined_df.ffill().bfill().fillna(0)
            
            # Add event data as binary features
            event_df = self.process_events(data["events"], combined_df.index)
            final_df = pd.concat([combined_df, event_df], axis=1)
            
            # Add cluster_issue_type as a column
            final_df["cluster_issue_type"] = cluster_issue_type
            
            # Save to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            issue_suffix = f"_{cluster_issue_type}" if cluster_issue_type else ""
            processed_file = f"data/processed/processed_metrics_{timestamp}{issue_suffix}.csv"
            final_df.to_csv(processed_file)
            print(f"Saved processed metrics to {processed_file}")
            return processed_file
        else:
            print("No metrics to process")
            return None
    
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
    raw_file = collector.collect_metrics(
        duration_minutes=args.duration,
        step=args.step,
        namespaces=args.namespaces,
        cluster_issue_type=args.cluster_issue_type
    )
    
    # Process metrics if requested
    if args.process and raw_file:
        processed_file = collector.process_metrics(raw_file)
        if processed_file:
            print(f"Data collection and processing complete.")
            return 0
    
    return 0

if __name__ == "__main__":
    main() 