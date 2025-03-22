import argparse
import kubernetes.client
import kubernetes.config
import time
import yaml
import random
import uuid
import sys
from datetime import datetime

def create_network_chaos_pod(namespace, latency_ms=0, packet_loss_percent=0, duration_seconds=300, pod_name=None):
    """Create a pod that introduces network chaos (latency, packet loss) in the cluster."""
    k8s_client = kubernetes.client.CoreV1Api()
    
    if pod_name is None:
        pod_name = f"network-chaos-{int(time.time())}-{str(uuid.uuid4())[:5]}"
    
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "app": "network-chaos",
                "scenario": "network-issues",
                "metric-collection": "enabled"
            },
            "annotations": {
                "prometheus.io/scrape": "true",
                "prometheus.io/port": "8080"
            }
        },
        "spec": {
            "containers": [{
                "name": "network-chaos",
                "image": "nicolaka/netshoot",
                "command": ["sh", "-c"],
                "args": [
                    f"tc qdisc add dev eth0 root netem delay {latency_ms}ms loss {packet_loss_percent}% && sleep {duration_seconds} && tc qdisc del dev eth0 root"
                ],
                "securityContext": {
                    "capabilities": {
                        "add": ["NET_ADMIN"]
                    }
                },
                "resources": {
                    "requests": {
                        "cpu": "100m",
                        "memory": "128Mi"
                    },
                    "limits": {
                        "cpu": "200m",
                        "memory": "256Mi"
                    }
                }
            }, {
                "name": "metrics",
                "image": "nginx:alpine",
                "ports": [{
                    "containerPort": 8080,
                    "name": "metrics"
                }]
            }],
            "restartPolicy": "Never"
        }
    }
    
    try:
        k8s_client.create_namespaced_pod(namespace, pod_manifest)
        print(f"Created network chaos pod '{pod_name}' in namespace {namespace}")
        return pod_name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating pod: {e}")
        return None

def run_scenario(namespace, num_pods, duration_seconds, pattern="random"):
    """Run a network issue scenario with multiple pods."""
    pods = []
    
    if pattern == "random":
        # Random network issues
        for i in range(num_pods):
            latency = random.randint(50, 500)
            loss = random.uniform(1, 15)
            pod_name = create_network_chaos_pod(namespace, latency, loss, duration_seconds)
            pods.append(pod_name)
    
    elif pattern == "gradual":
        # Gradually increasing network issues
        for i in range(num_pods):
            latency = 50 + (i * 450 // num_pods)
            loss = 1 + (i * 14 // num_pods)
            pod_name = create_network_chaos_pod(namespace, latency, loss, duration_seconds)
            pods.append(pod_name)
    
    elif pattern == "spike":
        # Create a spike in network issues
        for i in range(num_pods):
            # Most pods have mild issues
            if i < num_pods * 0.8:
                latency = random.randint(50, 100)
                loss = random.uniform(1, 3)
            # But a few have severe issues
            else:
                latency = random.randint(400, 500)
                loss = random.uniform(10, 15)
            pod_name = create_network_chaos_pod(namespace, latency, loss, duration_seconds)
            pods.append(pod_name)
    
    else:
        print(f"Unknown pattern: {pattern}")
        sys.exit(1)
    
    return pods

def wait_for_scenario_completion(namespace, pods, duration_seconds):
    """Wait for all pods in the scenario to complete."""
    k8s_client = kubernetes.client.CoreV1Api()
    
    print(f"Waiting for scenario to complete (up to {duration_seconds} seconds)...")
    end_time = time.time() + duration_seconds + 30  # Add buffer time
    
    while time.time() < end_time:
        all_completed = True
        for pod_name in pods:
            try:
                pod = k8s_client.read_namespaced_pod(pod_name, namespace)
                if pod.status.phase not in ["Succeeded", "Failed"]:
                    all_completed = False
                    break
            except kubernetes.client.rest.ApiException:
                # Pod might have been deleted
                continue
        
        if all_completed:
            print("All pods have completed")
            return
        
        time.sleep(10)
        print(".", end="", flush=True)
    
    print("\nTimeout waiting for pods to complete")

def create_monitoring_namespace_if_not_exists():
    """Create the monitoring namespace if it doesn't exist."""
    k8s_client = kubernetes.client.CoreV1Api()
    
    try:
        k8s_client.read_namespace(name="monitoring")
        print("Monitoring namespace already exists")
    except kubernetes.client.rest.ApiException:
        namespace_manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": "monitoring"
            }
        }
        k8s_client.create_namespace(namespace_manifest)
        print("Created monitoring namespace")

def create_service_monitor(namespace, pod_selector):
    """Create a ServiceMonitor to tell Prometheus to scrape our pods."""
    k8s_client = kubernetes.client.CustomObjectsApi()
    
    service_monitor = {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "ServiceMonitor",
        "metadata": {
            "name": "network-issues-monitor",
            "namespace": "monitoring"
        },
        "spec": {
            "selector": {
                "matchLabels": pod_selector
            },
            "endpoints": [{
                "port": "metrics",
                "interval": "15s"
            }],
            "namespaceSelector": {
                "matchNames": [namespace]
            }
        }
    }
    
    try:
        k8s_client.create_namespaced_custom_object(
            group="monitoring.coreos.com",
            version="v1",
            namespace="monitoring",
            plural="servicemonitors",
            body=service_monitor
        )
        print(f"Created ServiceMonitor in namespace 'monitoring'")
    except kubernetes.client.rest.ApiException as e:
        if e.status == 409:  # Already exists
            print("ServiceMonitor already exists")
        else:
            print(f"Error creating ServiceMonitor: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate network issues in a Kubernetes cluster")
    parser.add_argument("--namespace", default="default", help="Namespace to create network chaos pods in")
    parser.add_argument("--pods", type=int, default=5, help="Number of pods to create")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of network issues")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    kubernetes.config.load_kube_config()
    
    # Ensure monitoring namespace exists
    create_monitoring_namespace_if_not_exists()
    
    # Create pods according to the requested pattern
    print(f"Starting network issues scenario '{args.pattern}' with {args.pods} pods for {args.duration} seconds")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    pods = run_scenario(args.namespace, args.pods, args.duration, args.pattern)
    
    # Create ServiceMonitor for the pods
    create_service_monitor(args.namespace, {"app": "network-chaos"})
    
    # Wait for scenario to complete
    wait_for_scenario_completion(args.namespace, pods, args.duration)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Network issues scenario completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    print(f"To view metrics, access Grafana and query for metrics with 'pod=~\"network-chaos.*\"'") 