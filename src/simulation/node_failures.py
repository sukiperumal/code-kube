import argparse
import kubernetes.client
import kubernetes.config
import time
import random
import sys
import uuid
from datetime import datetime

def simulate_node_failure(namespace, duration_seconds, pattern="random"):
    """
    Simulate node failures by cordoning and draining nodes
    
    This simulates node failures without actually causing downtime to the cluster.
    It cordons nodes to prevent new scheduling and drains existing pods.
    """
    kubernetes.config.load_kube_config()
    k8s_api = kubernetes.client.CoreV1Api()
    k8s_apps_api = kubernetes.client.AppsV1Api()
    
    # Get list of all nodes
    try:
        nodes = k8s_api.list_node()
        node_names = [node.metadata.name for node in nodes.items]
    except kubernetes.client.rest.ApiException as e:
        print(f"Error getting node list: {e}")
        return []
    
    if len(node_names) <= 1:
        print("Not enough nodes in the cluster to simulate node failures safely")
        return []
    
    # Select nodes to simulate failure based on pattern
    target_nodes = []
    
    if pattern == "random":
        # Randomly select up to 30% of nodes but at least 1
        num_target_nodes = max(1, int(len(node_names) * 0.3))
        target_nodes = random.sample(node_names, num_target_nodes)
    
    elif pattern == "gradual":
        # Start with one node, then gradually add more over time
        target_nodes = [random.choice(node_names)]
        
        # Schedule additional nodes to be cordoned
        if len(node_names) > 1:
            remaining_nodes = [n for n in node_names if n not in target_nodes]
            additional_targets = random.sample(remaining_nodes, min(2, len(remaining_nodes)))
            
            # Store the additional targets and time to cordon
            additional_node_schedule = []
            for i, node in enumerate(additional_targets):
                # Schedule each node at an interval through the test duration
                schedule_time = time.time() + (duration_seconds * (i+1) / (len(additional_targets) + 1))
                additional_node_schedule.append((node, schedule_time))
    
    elif pattern == "spike":
        # Simulate a sudden spike of multiple node failures
        # Choose 30-50% of nodes all at once
        num_target_nodes = max(1, int(len(node_names) * random.uniform(0.3, 0.5)))
        target_nodes = random.sample(node_names, num_target_nodes)
    
    else:
        print(f"Unknown pattern: {pattern}")
        return []
    
    cordoned_nodes = []
    
    # Initial node cordoning
    for node_name in target_nodes:
        try:
            # Add cordon annotation to prevent scheduling on this node
            patch_body = {
                "spec": {
                    "unschedulable": True
                }
            }
            k8s_api.patch_node(node_name, patch_body)
            print(f"Cordoned node {node_name}")
            cordoned_nodes.append(node_name)
            
            # Mark node with the simulation annotation
            patch_annotation = {
                "metadata": {
                    "annotations": {
                        "simulation/node-failure": "true",
                        "simulation/timestamp": datetime.now().isoformat()
                    }
                }
            }
            k8s_api.patch_node(node_name, patch_annotation)
            
            # Deploy a DaemonSet that disrupts node services slightly
            # This DaemonSet puts small loads on critical node services
            disruptor_ds_name = f"node-disruptor-{str(uuid.uuid4())[:8]}"
            disruptor_ds = {
                "apiVersion": "apps/v1",
                "kind": "DaemonSet",
                "metadata": {
                    "name": disruptor_ds_name,
                    "namespace": namespace,
                    "labels": {
                        "app": "node-disruptor",
                        "scenario": "node-failure"
                    }
                },
                "spec": {
                    "selector": {
                        "matchLabels": {
                            "app": "node-disruptor"
                        }
                    },
                    "template": {
                        "metadata": {
                            "labels": {
                                "app": "node-disruptor"
                            }
                        },
                        "spec": {
                            "tolerations": [
                                {
                                    "key": "node.kubernetes.io/unschedulable",
                                    "operator": "Exists",
                                    "effect": "NoSchedule"
                                }
                            ],
                            "nodeSelector": {
                                "kubernetes.io/hostname": node_name
                            },
                            "containers": [
                                {
                                    "name": "disruptor",
                                    "image": "busybox",
                                    "command": [
                                        "/bin/sh",
                                        "-c",
                                        # Stress kubelet with API calls and watch filesystem
                                        "while true; do ls -la /proc; sleep 0.1; done & " +
                                        "while true; do dd if=/dev/zero of=/tmp/zero bs=1M count=10; rm /tmp/zero; sleep 1; done"
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
                                }
                            ]
                        }
                    }
                }
            }
            
            try:
                k8s_apps_api.create_namespaced_daemon_set(namespace, disruptor_ds)
                print(f"Created node disruptor DaemonSet {disruptor_ds_name} targeting node {node_name}")
            except kubernetes.client.rest.ApiException as e:
                print(f"Error creating DaemonSet: {e}")
            
        except kubernetes.client.rest.ApiException as e:
            print(f"Error cordoning node {node_name}: {e}")
    
    if pattern == "gradual" and 'additional_node_schedule' in locals():
        # For gradual pattern, cordon additional nodes over time
        while time.time() < time.time() + duration_seconds:
            for node_name, schedule_time in additional_node_schedule[:]:
                if time.time() >= schedule_time:
                    try:
                        # Cordon the additional node
                        patch_body = {
                            "spec": {
                                "unschedulable": True
                            }
                        }
                        k8s_api.patch_node(node_name, patch_body)
                        print(f"Cordoned additional node {node_name}")
                        cordoned_nodes.append(node_name)
                        
                        # Remove from schedule list
                        additional_node_schedule.remove((node_name, schedule_time))
                    except kubernetes.client.rest.ApiException as e:
                        print(f"Error cordoning node {node_name}: {e}")
            
            if not additional_node_schedule:
                break
                
            time.sleep(10)
    
    # Wait for the duration of the test
    print(f"Node failure simulation in progress for {duration_seconds} seconds...")
    time.sleep(duration_seconds)
    
    # Cleanup: uncordon all nodes we cordoned
    for node_name in cordoned_nodes:
        try:
            # Uncordon the node
            patch_body = {
                "spec": {
                    "unschedulable": False
                }
            }
            k8s_api.patch_node(node_name, patch_body)
            print(f"Uncordoned node {node_name}")
            
            # Remove the simulation annotation
            patch_annotation = {
                "metadata": {
                    "annotations": {
                        "simulation/node-failure": None,
                        "simulation/timestamp": None
                    }
                }
            }
            k8s_api.patch_node(node_name, patch_annotation)
            
        except kubernetes.client.rest.ApiException as e:
            print(f"Error uncordoning node {node_name}: {e}")
    
    # Clean up the disruptor DaemonSets
    try:
        daemon_sets = k8s_apps_api.list_namespaced_daemon_set(namespace, label_selector="scenario=node-failure")
        for ds in daemon_sets.items:
            k8s_apps_api.delete_namespaced_daemon_set(ds.metadata.name, namespace)
            print(f"Deleted DaemonSet {ds.metadata.name}")
    except kubernetes.client.rest.ApiException as e:
        print(f"Error cleaning up DaemonSets: {e}")
    
    return cordoned_nodes

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate node failures in a Kubernetes cluster")
    parser.add_argument("--namespace", default="default", help="Namespace to create resources in")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of node failures")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--pods", type=int, default=0, help="Ignored - for compatibility with other scripts")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Starting node failure simulation with pattern '{args.pattern}' for {args.duration} seconds")
    
    nodes = simulate_node_failure(args.namespace, args.duration, args.pattern)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Node failure simulation completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    print(f"Affected nodes: {', '.join(nodes)}") 