import argparse
import kubernetes.client
import kubernetes.config
import time
import random
import uuid
import sys
from datetime import datetime

def create_app_namespace(namespace):
    """Create a namespace if it doesn't exist"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    try:
        k8s_client.read_namespace(name=namespace)
        print(f"Namespace '{namespace}' already exists")
    except kubernetes.client.rest.ApiException:
        namespace_manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": namespace
            }
        }
        k8s_client.create_namespace(namespace_manifest)
        print(f"Created namespace '{namespace}'")

def create_app_deployment(namespace, name, replicas=3, image="nginx:alpine", labels=None, ports=None):
    """Create a deployment that will be used in network policy tests"""
    k8s_apps_api = kubernetes.client.AppsV1Api()
    
    if labels is None:
        labels = {"app": name}
    
    if ports is None:
        ports = [80]
    
    container_ports = [{"containerPort": port} for port in ports]
    
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "scenario": "network-policy-issues"
            }
        },
        "spec": {
            "replicas": replicas,
            "selector": {
                "matchLabels": labels
            },
            "template": {
                "metadata": {
                    "labels": labels
                },
                "spec": {
                    "containers": [{
                        "name": "app",
                        "image": image,
                        "ports": container_ports,
                        "command": ["sh", "-c"],
                        "args": ["while true; do nc -l -p 8080 || true; done &" +
                                  "nginx -g 'daemon off;'"]
                    }]
                }
            }
        }
    }
    
    try:
        k8s_apps_api.create_namespaced_deployment(namespace, deployment)
        print(f"Created deployment '{name}' in namespace '{namespace}'")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating deployment: {e}")
        return None

def create_app_service(namespace, name, deployment_name, labels=None, ports=None):
    """Create a service for the deployment"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    if labels is None:
        labels = {"app": deployment_name}
    
    if ports is None:
        ports = [{"port": 80, "targetPort": 80}]
    
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "scenario": "network-policy-issues"
            }
        },
        "spec": {
            "selector": labels,
            "ports": ports
        }
    }
    
    try:
        k8s_client.create_namespaced_service(namespace, service)
        print(f"Created service '{name}' in namespace '{namespace}'")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating service: {e}")
        return None

def create_network_policy(namespace, name, pod_selector, ingress_rules=None, egress_rules=None, policy_types=None):
    """Create a NetworkPolicy resource"""
    k8s_network_api = kubernetes.client.NetworkingV1Api()
    
    if policy_types is None:
        policy_types = ["Ingress", "Egress"]
    
    spec = {
        "podSelector": pod_selector,
        "policyTypes": policy_types
    }
    
    if ingress_rules:
        spec["ingress"] = ingress_rules
    
    if egress_rules:
        spec["egress"] = egress_rules
    
    network_policy = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "scenario": "network-policy-issues"
            }
        },
        "spec": spec
    }
    
    try:
        k8s_network_api.create_namespaced_network_policy(namespace, network_policy)
        print(f"Created NetworkPolicy '{name}' in namespace '{namespace}'")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating NetworkPolicy: {e}")
        return None

def create_tester_pod(namespace, name, target_service, target_namespace, wait_ready=True):
    """Create a pod that tests connectivity to the service"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": "connectivity-tester",
                "scenario": "network-policy-issues"
            }
        },
        "spec": {
            "containers": [{
                "name": "tester",
                "image": "nicolaka/netshoot",
                "command": ["sh", "-c", "while true; do sleep 10; done"],
                "readinessProbe": {
                    "exec": {
                        "command": ["sh", "-c", "nc -z -w 1 " + target_service + "." + target_namespace + ".svc.cluster.local 80"]
                    },
                    "initialDelaySeconds": 5,
                    "periodSeconds": 10
                }
            }]
        }
    }
    
    try:
        k8s_client.create_namespaced_pod(namespace, pod)
        print(f"Created tester pod '{name}' in namespace '{namespace}'")
        
        if wait_ready:
            # Wait for the pod to be ready (up to 60 seconds)
            print(f"Waiting for pod '{name}' to be ready...")
            start_time = time.time()
            while time.time() - start_time < 60:
                pod_status = k8s_client.read_namespaced_pod_status(name, namespace)
                if pod_status.status.container_statuses and pod_status.status.container_statuses[0].ready:
                    print(f"Pod '{name}' is ready")
                    return name
                time.sleep(5)
            print(f"Timeout waiting for pod '{name}' to be ready")
            return name
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating pod: {e}")
        return None

def run_conflicting_policies_scenario(namespace, num_apps, duration_seconds, pattern="random"):
    """
    Create a scenario with conflicting network policies.
    Returns a dict of created resources.
    """
    k8s_network_api = kubernetes.client.NetworkingV1Api()
    
    created_resources = {
        "namespaces": [],
        "deployments": [],
        "services": [],
        "policies": [],
        "tester_pods": []
    }
    
    timestamp = int(time.time())
    uid = str(uuid.uuid4())[:5]
    
    # Create multiple namespaces for different apps
    namespaces = []
    for i in range(3):  # Use a few different namespaces
        ns_name = f"{namespace}-{i}"
        create_app_namespace(ns_name)
        namespaces.append(ns_name)
        created_resources["namespaces"].append(ns_name)
    
    # Create multiple app deployments and services
    apps = []
    for i in range(num_apps):
        app_ns = random.choice(namespaces)
        app_name = f"app-{timestamp}-{i}-{uid}"
        labels = {
            "app": app_name,
            "tier": random.choice(["frontend", "backend", "database"]),
            "environment": random.choice(["dev", "prod", "test"])
        }
        
        if create_app_deployment(app_ns, app_name, replicas=2, labels=labels):
            created_resources["deployments"].append((app_ns, app_name))
            
            svc_name = f"svc-{app_name}"
            if create_app_service(app_ns, svc_name, app_name, labels=labels):
                created_resources["services"].append((app_ns, svc_name))
                apps.append((app_ns, app_name, svc_name, labels))
    
    # Create tester pods that try to connect to the services
    for i, (app_ns, app_name, svc_name, _) in enumerate(apps):
        for j, ns in enumerate(namespaces):
            if i % 3 == j:  # Only create some testers to avoid too many pods
                tester_name = f"tester-{timestamp}-{i}-{j}-{uid}"
                if create_tester_pod(ns, tester_name, svc_name, app_ns, wait_ready=False):
                    created_resources["tester_pods"].append((ns, tester_name))
    
    # Now create network policies based on the pattern
    if pattern == "random":
        # Create random network policies, some of which will conflict
        for app_ns, app_name, _, labels in random.sample(apps, min(len(apps), 5)):
            policy_name = f"netpol-{app_name}-random"
            
            # Random ingress rules
            ingress_rules = []
            if random.random() < 0.7:  # 70% chance to have ingress rules
                from_rules = []
                
                # Add namespace selectors
                if random.random() < 0.5:
                    from_rules.append({
                        "namespaceSelector": {
                            "matchLabels": {
                                "kubernetes.io/metadata.name": random.choice(namespaces)
                            }
                        }
                    })
                
                # Add pod selectors
                if random.random() < 0.7:
                    # Choose a random label to select on
                    label_key = random.choice(list(labels.keys()))
                    from_rules.append({
                        "podSelector": {
                            "matchLabels": {
                                label_key: labels[label_key]
                            }
                        }
                    })
                
                ingress_rules.append({"from": from_rules})
            
            # Random egress rules
            egress_rules = []
            if random.random() < 0.5:  # 50% chance to have egress rules
                to_rules = []
                
                # Add namespace selectors
                if random.random() < 0.3:
                    to_rules.append({
                        "namespaceSelector": {
                            "matchLabels": {
                                "kubernetes.io/metadata.name": random.choice(namespaces)
                            }
                        }
                    })
                
                # Add pod selectors
                if random.random() < 0.6:
                    # Choose a random label to select on
                    other_app = random.choice(apps)
                    other_labels = other_app[3]
                    label_key = random.choice(list(other_labels.keys()))
                    to_rules.append({
                        "podSelector": {
                            "matchLabels": {
                                label_key: other_labels[label_key]
                            }
                        }
                    })
                
                # Block all egress sometimes
                if not to_rules and random.random() < 0.3:
                    egress_rules.append({})  # Empty 'to' means block all
                else:
                    egress_rules.append({"to": to_rules})
            
            # Create the policy
            pod_selector = {"matchLabels": {"app": app_name}}
            if create_network_policy(app_ns, policy_name, pod_selector, ingress_rules, egress_rules):
                created_resources["policies"].append((app_ns, policy_name))
        
        # Create a few "deny all" policies that will conflict
        for ns in random.sample(namespaces, min(len(namespaces), 2)):
            deny_policy_name = f"netpol-deny-all-{timestamp}-{uid}"
            pod_selector = {}  # Empty selector means all pods
            if create_network_policy(ns, deny_policy_name, pod_selector, [], []):
                created_resources["policies"].append((ns, deny_policy_name))
    
    elif pattern == "gradual":
        # Start with permissive policies, then gradually add more restrictive ones
        
        # Phase 1: Add some basic policies allowing internal communication
        time_per_phase = duration_seconds / 3
        
        for app_ns, app_name, _, labels in apps:
            policy_name = f"netpol-{app_name}-phase1"
            
            # Allow traffic from the same namespace
            ingress_rules = [{
                "from": [{
                    "podSelector": {}  # Empty selector means all pods in the namespace
                }]
            }]
            
            pod_selector = {"matchLabels": {"app": app_name}}
            if create_network_policy(app_ns, policy_name, pod_selector, ingress_rules):
                created_resources["policies"].append((app_ns, policy_name))
        
        # Wait before adding more policies
        print(f"Phase 1 policies created. Waiting {int(time_per_phase)} seconds before phase 2...")
        time.sleep(time_per_phase)
        
        # Phase 2: Add more specific policies that are slightly more restrictive
        for app_ns, app_name, _, labels in apps:
            policy_name = f"netpol-{app_name}-phase2"
            
            # Only allow traffic from specific tiers
            if "tier" in labels:
                if labels["tier"] == "frontend":
                    # Frontend can receive traffic from anywhere
                    ingress_rules = [{}]
                elif labels["tier"] == "backend":
                    # Backend only from frontend
                    ingress_rules = [{
                        "from": [{
                            "podSelector": {
                                "matchLabels": {
                                    "tier": "frontend"
                                }
                            }
                        }]
                    }]
                else:
                    # Database only from backend
                    ingress_rules = [{
                        "from": [{
                            "podSelector": {
                                "matchLabels": {
                                    "tier": "backend"
                                }
                            }
                        }]
                    }]
                
                pod_selector = {"matchLabels": {"app": app_name}}
                if create_network_policy(app_ns, policy_name, pod_selector, ingress_rules):
                    created_resources["policies"].append((app_ns, policy_name))
        
        # Wait before adding final restrictive policies
        print(f"Phase 2 policies created. Waiting {int(time_per_phase)} seconds before phase 3...")
        time.sleep(time_per_phase)
        
        # Phase 3: Add conflicting deny-all policies
        for ns in namespaces:
            deny_policy_name = f"netpol-deny-all-{timestamp}-{uid}"
            pod_selector = {}  # Empty selector means all pods
            if create_network_policy(ns, deny_policy_name, pod_selector, [], []):
                created_resources["policies"].append((ns, deny_policy_name))
    
    elif pattern == "spike":
        # Suddenly add a large number of conflicting policies
        
        # First, add some basic allowing policies
        for app_ns, app_name, _, labels in apps:
            allow_policy_name = f"netpol-allow-{app_name}"
            
            # Allow specific traffic
            ingress_rules = [{
                "from": [{
                    "podSelector": {
                        "matchLabels": {
                            "app": "connectivity-tester"
                        }
                    }
                }]
            }]
            
            pod_selector = {"matchLabels": {"app": app_name}}
            if create_network_policy(app_ns, allow_policy_name, pod_selector, ingress_rules):
                created_resources["policies"].append((app_ns, allow_policy_name))
        
        # Wait a bit to establish baseline
        wait_time = min(30, duration_seconds // 3)
        print(f"Basic policies created. Waiting {wait_time} seconds before spike...")
        time.sleep(wait_time)
        
        # Now add a spike of conflicting policies all at once
        for app_ns, app_name, _, labels in apps:
            # Add a restrictive policy for the app
            deny_policy_name = f"netpol-restrict-{app_name}"
            
            # Block nearly all traffic
            ingress_rules = []  # Empty means no ingress rules = no incoming traffic
            
            pod_selector = {"matchLabels": {"app": app_name}}
            if create_network_policy(app_ns, deny_policy_name, pod_selector, ingress_rules):
                created_resources["policies"].append((app_ns, deny_policy_name))
        
        # Add deny-all policies for extra measure
        for ns in namespaces:
            deny_all_policy_name = f"netpol-deny-all-{ns}"
            pod_selector = {}  # Empty means all pods
            if create_network_policy(ns, deny_all_policy_name, pod_selector, [], []):
                created_resources["policies"].append((ns, deny_all_policy_name))
    
    else:
        print(f"Unknown pattern: {pattern}")
        return created_resources
    
    # Wait for the remaining duration
    remaining_time = duration_seconds - (time.time() - timestamp)
    if remaining_time > 0:
        print(f"Scenario running. Waiting {int(remaining_time)} more seconds...")
        time.sleep(remaining_time)
    
    return created_resources

def cleanup_resources(resources):
    """Clean up all created resources"""
    k8s_client = kubernetes.client.CoreV1Api()
    k8s_apps_api = kubernetes.client.AppsV1Api()
    k8s_network_api = kubernetes.client.NetworkingV1Api()
    
    # Delete network policies
    for ns, policy_name in resources["policies"]:
        try:
            k8s_network_api.delete_namespaced_network_policy(policy_name, ns)
            print(f"Deleted NetworkPolicy {policy_name} in namespace {ns}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting NetworkPolicy {policy_name}: {e}")
    
    # Delete tester pods
    for ns, pod_name in resources["tester_pods"]:
        try:
            k8s_client.delete_namespaced_pod(pod_name, ns)
            print(f"Deleted pod {pod_name} in namespace {ns}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting pod {pod_name}: {e}")
    
    # Delete services
    for ns, service_name in resources["services"]:
        try:
            k8s_client.delete_namespaced_service(service_name, ns)
            print(f"Deleted service {service_name} in namespace {ns}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting service {service_name}: {e}")
    
    # Delete deployments
    for ns, deployment_name in resources["deployments"]:
        try:
            k8s_apps_api.delete_namespaced_deployment(deployment_name, ns)
            print(f"Deleted deployment {deployment_name} in namespace {ns}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting deployment {deployment_name}: {e}")
    
    # Don't delete namespaces as they might be used by other tests
    # Instead just report them
    print(f"Note: The following namespaces were used but not deleted: {', '.join(resources['namespaces'])}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate network policy conflicts in a Kubernetes cluster")
    parser.add_argument("--namespace", default="network-policy-test", help="Base namespace to create resources in")
    parser.add_argument("--pods", type=int, default=5, help="Number of app deployments to create")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of network policy conflicts")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--cleanup", action="store_true", help="Clean up resources after completion")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    kubernetes.config.load_kube_config()
    
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Starting network policy conflicts simulation with pattern '{args.pattern}' for {args.duration} seconds")
    
    resources = run_conflicting_policies_scenario(args.namespace, args.pods, args.duration, args.pattern)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Network policy conflicts simulation completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    
    # Print summary of created resources
    print("\nCreated resources:")
    for res_type, res_list in resources.items():
        print(f"- {res_type}: {len(res_list)}")
    
    if args.cleanup:
        print("\nCleaning up resources...")
        cleanup_resources(resources) 