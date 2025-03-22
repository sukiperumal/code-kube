import argparse
import kubernetes.client
import kubernetes.config
import time
import yaml
import random
import uuid
import sys
from datetime import datetime

def create_stress_pod(namespace, cpu_load, memory_load, duration_seconds, pod_name=None):
    """Create a pod that consumes specified CPU and memory resources."""
    k8s_client = kubernetes.client.CoreV1Api()
    
    if pod_name is None:
        pod_name = f"stress-test-{int(time.time())}-{str(uuid.uuid4())[:5]}"
    
    # Calculate memory amount for vm-bytes
    # Keep it lower than the limit to avoid OOM kills
    vm_bytes = max(memory_load * 64, 64)
    
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "app": "stress-test",
                "scenario": "resource-exhaustion",
                "metric-collection": "enabled"
            },
            "annotations": {
                "prometheus.io/scrape": "true",
                "prometheus.io/port": "8080"
            }
        },
        "spec": {
            "containers": [{
                "name": "stress",
                "image": "polinux/stress",
                "command": ["stress"],
                "args": [
                    "--cpu", str(cpu_load),
                    "--vm", str(memory_load),
                    "--vm-bytes", f"{vm_bytes}M",
                    "--timeout", str(duration_seconds)
                ],
                "resources": {
                    "requests": {
                        "cpu": f"{max(cpu_load * 100, 100)}m",
                        "memory": f"{max(memory_load * 128, 128)}Mi"
                    },
                    "limits": {
                        "cpu": f"{max(cpu_load * 200, 200)}m",
                        "memory": f"{max(memory_load * 256, 256)}Mi"
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
        print(f"Created stress test pod '{pod_name}' in namespace {namespace}")
        return pod_name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating pod: {e}")
        return None

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
            "name": "resource-exhaustion-monitor",
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

def run_scenario(namespace, num_pods, duration_seconds, pattern="random"):
    """Run a resource exhaustion scenario with multiple pods."""
    pods = []
    
    if pattern == "random":
        # Random resource allocation
        for i in range(num_pods):
            cpu = random.randint(1, 4)
            memory = random.randint(1, 4)
            pod_name = create_stress_pod(namespace, cpu, memory, duration_seconds)
            pods.append(pod_name)
    
    elif pattern == "gradual":
        # Gradually increasing load
        for i in range(num_pods):
            cpu = 1 + (i * 4 // num_pods)
            memory = 1 + (i * 4 // num_pods)
            pod_name = create_stress_pod(namespace, cpu, memory, duration_seconds)
            pods.append(pod_name)
    
    elif pattern == "spike":
        # Create a spike in resource usage
        for i in range(num_pods):
            # Most pods use minimal resources
            if i < num_pods * 0.8:
                cpu = 1
                memory = 1
            # But a few use a lot
            else:
                cpu = 4
                memory = 4
            pod_name = create_stress_pod(namespace, cpu, memory, duration_seconds)
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate resource exhaustion in a Kubernetes cluster")
    parser.add_argument("--namespace", default="default", help="Namespace to create stress pods in")
    parser.add_argument("--pods", type=int, default=5, help="Number of pods to create")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of resource allocation")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    kubernetes.config.load_kube_config()
    
    # Ensure monitoring namespace exists
    create_monitoring_namespace_if_not_exists()
    
    # Create pods according to the requested pattern
    print(f"Starting resource exhaustion scenario '{args.pattern}' with {args.pods} pods for {args.duration} seconds")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    pods = run_scenario(args.namespace, args.pods, args.duration, args.pattern)
    
    # Create ServiceMonitor for the pods
    create_service_monitor(args.namespace, {"app": "stress-test"})
    
    # Wait for scenario to complete
    wait_for_scenario_completion(args.namespace, pods, args.duration)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Resource exhaustion scenario completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    print(f"To view metrics, access Grafana and query for metrics with 'pod=~\"stress-test.*\"'")