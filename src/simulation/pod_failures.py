import argparse
import kubernetes.client
import kubernetes.config
import time
import yaml
import random
import uuid
import sys
from datetime import datetime

def create_unstable_pod(namespace, crash_probability=0.3, crash_interval=60, duration_seconds=300, pod_name=None):
    """Create a pod that has a probability of crashing at regular intervals."""
    k8s_client = kubernetes.client.CoreV1Api()
    
    if pod_name is None:
        pod_name = f"unstable-pod-{int(time.time())}-{str(uuid.uuid4())[:5]}"
    
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "app": "unstable-pod",
                "scenario": "pod-failures",
                "metric-collection": "enabled"
            },
            "annotations": {
                "prometheus.io/scrape": "true",
                "prometheus.io/port": "8080"
            }
        },
        "spec": {
            "containers": [{
                "name": "unstable",
                "image": "alpine",
                "command": ["sh", "-c"],
                "args": [
                    f"while true; do if [ $(awk 'BEGIN{{print rand()}}') -lt {crash_probability} ]; then echo 'Simulating crash'; exit 1; else echo 'Running normally'; fi; sleep {crash_interval}; done"
                ],
                "resources": {
                    "requests": {
                        "cpu": "50m",
                        "memory": "64Mi"
                    },
                    "limits": {
                        "cpu": "100m",
                        "memory": "128Mi"
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
            "restartPolicy": "OnFailure"
        }
    }
    
    try:
        k8s_client.create_namespaced_pod(namespace, pod_manifest)
        print(f"Created unstable pod '{pod_name}' in namespace {namespace}")
        return pod_name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating pod: {e}")
        return None

def create_deployment_with_unstable_pods(namespace, replicas=3, crash_probability=0.3, crash_interval=60, duration_seconds=300, deployment_name=None):
    """Create a deployment with pods that have a probability of crashing."""
    k8s_client = kubernetes.client.AppsV1Api()
    
    if deployment_name is None:
        deployment_name = f"unstable-deployment-{int(time.time())}-{str(uuid.uuid4())[:5]}"
    
    deployment_manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": namespace,
            "labels": {
                "app": "unstable-deployment",
                "scenario": "pod-failures"
            }
        },
        "spec": {
            "replicas": replicas,
            "selector": {
                "matchLabels": {
                    "app": "unstable-deployment"
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "unstable-deployment",
                        "scenario": "pod-failures",
                        "metric-collection": "enabled"
                    },
                    "annotations": {
                        "prometheus.io/scrape": "true",
                        "prometheus.io/port": "8080"
                    }
                },
                "spec": {
                    "containers": [{
                        "name": "unstable",
                        "image": "alpine",
                        "command": ["sh", "-c"],
                        "args": [
                            f"while true; do if [ $(awk 'BEGIN{{print rand()}}') -lt {crash_probability} ]; then echo 'Simulating crash'; exit 1; else echo 'Running normally'; fi; sleep {crash_interval}; done"
                        ],
                        "resources": {
                            "requests": {
                                "cpu": "50m",
                                "memory": "64Mi"
                            },
                            "limits": {
                                "cpu": "100m",
                                "memory": "128Mi"
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
                    "restartPolicy": "Always"
                }
            }
        }
    }
    
    try:
        k8s_client.create_namespaced_deployment(namespace, deployment_manifest)
        print(f"Created unstable deployment '{deployment_name}' with {replicas} replicas in namespace {namespace}")
        return deployment_name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating deployment: {e}")
        return None

def run_scenario(namespace, num_pods, num_deployments, replicas_per_deployment, duration_seconds, pattern="random"):
    """Run a pod failure scenario with individual pods and deployments."""
    pods = []
    deployments = []
    
    if pattern == "random":
        # Random failure probabilities
        for i in range(num_pods):
            probability = random.uniform(0.1, 0.5)
            interval = random.randint(30, 120)
            pod_name = create_unstable_pod(namespace, probability, interval, duration_seconds)
            pods.append(pod_name)
        
        for i in range(num_deployments):
            probability = random.uniform(0.1, 0.5)
            interval = random.randint(30, 120)
            deployment_name = create_deployment_with_unstable_pods(
                namespace, replicas_per_deployment, probability, interval, duration_seconds
            )
            deployments.append(deployment_name)
    
    elif pattern == "gradual":
        # Gradually increasing failure probability
        for i in range(num_pods):
            probability = 0.1 + (i * 0.4 / max(1, num_pods - 1))
            interval = 120 - (i * 90 / max(1, num_pods - 1))
            pod_name = create_unstable_pod(namespace, probability, interval, duration_seconds)
            pods.append(pod_name)
        
        for i in range(num_deployments):
            probability = 0.1 + (i * 0.4 / max(1, num_deployments - 1))
            interval = 120 - (i * 90 / max(1, num_deployments - 1))
            deployment_name = create_deployment_with_unstable_pods(
                namespace, replicas_per_deployment, probability, interval, duration_seconds
            )
            deployments.append(deployment_name)
    
    elif pattern == "spike":
        # Create a spike in pod failures
        for i in range(num_pods):
            # Most pods are fairly stable
            if i < num_pods * 0.8:
                probability = random.uniform(0.1, 0.2)
                interval = random.randint(60, 120)
            # But a few are very unstable
            else:
                probability = random.uniform(0.4, 0.5)
                interval = random.randint(30, 60)
            pod_name = create_unstable_pod(namespace, probability, interval, duration_seconds)
            pods.append(pod_name)
        
        for i in range(num_deployments):
            # Most deployments are fairly stable
            if i < num_deployments * 0.8:
                probability = random.uniform(0.1, 0.2)
                interval = random.randint(60, 120)
            # But a few are very unstable
            else:
                probability = random.uniform(0.4, 0.5)
                interval = random.randint(30, 60)
            deployment_name = create_deployment_with_unstable_pods(
                namespace, replicas_per_deployment, probability, interval, duration_seconds
            )
            deployments.append(deployment_name)
    
    else:
        print(f"Unknown pattern: {pattern}")
        sys.exit(1)
    
    return pods, deployments

def wait_for_scenario_duration(duration_seconds):
    """Wait for the specified duration."""
    print(f"Running pod failure scenario for {duration_seconds} seconds...")
    time.sleep(duration_seconds)

def cleanup_resources(namespace, pods, deployments):
    """Clean up the resources created for the scenario."""
    k8s_client_core = kubernetes.client.CoreV1Api()
    k8s_client_apps = kubernetes.client.AppsV1Api()
    
    for pod_name in pods:
        try:
            k8s_client_core.delete_namespaced_pod(pod_name, namespace)
            print(f"Deleted pod '{pod_name}'")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting pod '{pod_name}': {e}")
    
    for deployment_name in deployments:
        try:
            k8s_client_apps.delete_namespaced_deployment(deployment_name, namespace)
            print(f"Deleted deployment '{deployment_name}'")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting deployment '{deployment_name}': {e}")

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
            "name": "pod-failures-monitor",
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
    parser = argparse.ArgumentParser(description="Simulate pod failures in a Kubernetes cluster")
    parser.add_argument("--namespace", default="default", help="Namespace to create unstable pods in")
    parser.add_argument("--pods", type=int, default=5, help="Number of individual pods to create")
    parser.add_argument("--deployments", type=int, default=2, help="Number of deployments to create")
    parser.add_argument("--replicas", type=int, default=3, help="Number of replicas per deployment")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of pod failures")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--cleanup", action="store_true", help="Clean up resources after scenario completes")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    kubernetes.config.load_kube_config()
    
    # Ensure monitoring namespace exists
    create_monitoring_namespace_if_not_exists()
    
    # Create pods and deployments according to the requested pattern
    print(f"Starting pod failure scenario '{args.pattern}' with {args.pods} pods, {args.deployments} deployments, {args.replicas} replicas each for {args.duration} seconds")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    pods, deployments = run_scenario(args.namespace, args.pods, args.deployments, args.replicas, args.duration, args.pattern)
    
    # Create ServiceMonitor for the pods
    create_service_monitor(args.namespace, {"scenario": "pod-failures"})
    
    # Wait for the specified duration
    wait_for_scenario_duration(args.duration)
    
    # Clean up resources if requested
    if args.cleanup:
        cleanup_resources(args.namespace, pods, deployments)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Pod failure scenario completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    print(f"To view metrics, access Grafana and query for metrics with 'scenario=\"pod-failures\"'") 