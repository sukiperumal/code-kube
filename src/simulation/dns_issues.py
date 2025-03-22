import argparse
import kubernetes.client
import kubernetes.config
import time
import random
import uuid
import sys
from datetime import datetime

def create_dns_chaos_pod(namespace, pod_name=None, delay_ms=0, error_rate_percent=0, duration_seconds=300):
    """Create a pod that interferes with DNS resolution"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    if pod_name is None:
        pod_name = f"dns-chaos-{int(time.time())}-{str(uuid.uuid4())[:5]}"
    
    # Create a pod that will spam DNS queries to CoreDNS
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "app": "dns-chaos",
                "scenario": "dns-issues"
            }
        },
        "spec": {
            "hostNetwork": True,  # To have more direct impact on the DNS infrastructure
            "containers": [{
                "name": "dns-chaos",
                "image": "nicolaka/netshoot",
                "command": ["/bin/bash"],
                "args": [
                    "-c",
                    # Generate DNS traffic with random non-existent domains
                    f"""
                    while true; do
                        # Generate random domain
                        domain="random-$RANDOM-$RANDOM-$RANDOM.example.internal"
                        
                        # Introduce artificial delay
                        if [ {delay_ms} -gt 0 ]; then
                            sleep $(echo "scale=3; {delay_ms}/1000" | bc)
                        fi
                        
                        # Determine if we should trigger an error
                        if [ $(($RANDOM % 100)) -lt {error_rate_percent} ]; then
                            echo "Triggering DNS error"
                            # Corrupt /etc/resolv.conf temporarily
                            cp /etc/resolv.conf /tmp/resolv.conf.bak
                            echo "nameserver 1.2.3.4" > /etc/resolv.conf
                            dig $domain || true
                            mv /tmp/resolv.conf.bak /etc/resolv.conf
                        else
                            # Normal DNS query to non-existent domain
                            dig $domain || true
                        fi
                        
                        # Sleep briefly to avoid overwhelming the system
                        sleep 0.01
                    done &
                    
                    # Run for specified duration and then exit
                    sleep {duration_seconds}
                    """
                ],
                "securityContext": {
                    "privileged": True  # Needed to modify resolv.conf
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
            }],
            "restartPolicy": "Never"
        }
    }
    
    try:
        k8s_client.create_namespaced_pod(namespace, pod_manifest)
        print(f"Created DNS chaos pod '{pod_name}' in namespace {namespace}")
        return pod_name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating pod: {e}")
        return None

def create_dns_consumer_pods(namespace, count=5, pod_prefix=None, query_interval_ms=1000):
    """Create pods that will make legitimate DNS queries and be affected by DNS issues"""
    k8s_client = kubernetes.client.CoreV1Api()
    pod_names = []
    
    if pod_prefix is None:
        pod_prefix = f"dns-consumer-{int(time.time())}"
    
    for i in range(count):
        pod_name = f"{pod_prefix}-{i}"
        
        # Create services for the pods to discover
        service_name = f"svc-{pod_name}"
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": service_name,
                "namespace": namespace
            },
            "spec": {
                "selector": {
                    "app": f"dns-consumer-{i}"
                },
                "ports": [{
                    "port": 80,
                    "targetPort": 80
                }]
            }
        }
        
        try:
            k8s_client.create_namespaced_service(namespace, service)
            print(f"Created service '{service_name}' in namespace {namespace}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error creating service: {e}")
        
        # Create a pod that will continuously do DNS lookups
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": namespace,
                "labels": {
                    "app": f"dns-consumer-{i}",
                    "scenario": "dns-issues"
                }
            },
            "spec": {
                "containers": [{
                    "name": "dns-lookup",
                    "image": "nicolaka/netshoot",
                    "command": ["/bin/bash"],
                    "args": [
                        "-c",
                        # Do DNS lookups of Kubernetes services and external domains
                        f"""
                        while true; do
                            # Query Kubernetes service with different levels of FQDN
                            dig {service_name} || true
                            dig {service_name}.{namespace} || true
                            dig {service_name}.{namespace}.svc.cluster.local || true
                            
                            # Also query external domains
                            dig kubernetes.io || true
                            dig google.com || true
                            
                            # Sleep between queries
                            sleep $(echo "scale=3; {query_interval_ms}/1000" | bc)
                        done
                        """
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
                }]
            }
        }
        
        try:
            k8s_client.create_namespaced_pod(namespace, pod_manifest)
            print(f"Created DNS consumer pod '{pod_name}' in namespace {namespace}")
            pod_names.append(pod_name)
        except kubernetes.client.rest.ApiException as e:
            print(f"Error creating pod: {e}")
    
    return pod_names

def run_dns_issue_scenario(namespace, num_pods, duration_seconds, pattern="random"):
    """Run a scenario with DNS resolution issues"""
    created_resources = {
        "chaos_pods": [],
        "consumer_pods": [],
        "services": []
    }
    
    timestamp = int(time.time())
    consumer_prefix = f"dns-consumer-{timestamp}"
    
    # Create pods that will be affected by DNS issues
    print(f"Creating {num_pods} DNS consumer pods...")
    consumer_pods = create_dns_consumer_pods(namespace, num_pods, consumer_prefix)
    created_resources["consumer_pods"] = consumer_pods
    created_resources["services"] = [f"svc-{pod}" for pod in consumer_pods]
    
    # Create pods that cause DNS issues based on the pattern
    if pattern == "random":
        # Random DNS issues with varying severity
        chaos_pods_count = max(1, num_pods // 2)
        
        for i in range(chaos_pods_count):
            delay_ms = random.randint(0, 500)  # 0-500ms delay
            error_rate = random.randint(0, 30)  # 0-30% error rate
            
            pod_name = f"dns-chaos-{timestamp}-{i}"
            pod = create_dns_chaos_pod(
                namespace, 
                pod_name=pod_name,
                delay_ms=delay_ms,
                error_rate_percent=error_rate,
                duration_seconds=duration_seconds
            )
            
            if pod:
                created_resources["chaos_pods"].append(pod)
    
    elif pattern == "gradual":
        # Start with mild DNS issues and gradually increase
        steps = min(5, num_pods)
        base_duration = duration_seconds // steps
        
        for i in range(steps):
            # Gradually increase delay and error rate
            delay_ms = int((i+1) * 100)  # 100ms, 200ms, 300ms, etc.
            error_rate = int((i+1) * 6)   # 6%, 12%, 18%, etc.
            step_duration = base_duration
            
            pod_name = f"dns-chaos-{timestamp}-step{i}"
            pod = create_dns_chaos_pod(
                namespace, 
                pod_name=pod_name,
                delay_ms=delay_ms,
                error_rate_percent=error_rate,
                duration_seconds=step_duration
            )
            
            if pod:
                created_resources["chaos_pods"].append(pod)
            
            # Wait for this step to complete before increasing load
            if i < steps - 1:  # Don't wait after the last step
                print(f"Waiting for step {i+1}/{steps} to complete...")
                time.sleep(step_duration)
    
    elif pattern == "spike":
        # Sudden severe DNS issues
        pod_name = f"dns-chaos-{timestamp}-spike"
        pod = create_dns_chaos_pod(
            namespace, 
            pod_name=pod_name,
            delay_ms=1000,  # 1 second delay
            error_rate_percent=50,  # 50% error rate
            duration_seconds=duration_seconds
        )
        
        if pod:
            created_resources["chaos_pods"].append(pod)
        
        # Add a second pod mid-way for an even bigger spike
        if duration_seconds > 60:
            time.sleep(duration_seconds // 2)
            
            pod_name_2 = f"dns-chaos-{timestamp}-spike2"
            pod_2 = create_dns_chaos_pod(
                namespace, 
                pod_name=pod_name_2,
                delay_ms=2000,  # 2 second delay
                error_rate_percent=70,  # 70% error rate
                duration_seconds=duration_seconds // 2
            )
            
            if pod_2:
                created_resources["chaos_pods"].append(pod_2)
    
    else:
        print(f"Unknown pattern: {pattern}")
        return created_resources
    
    # Wait for the dns chaos pods to complete
    k8s_client = kubernetes.client.CoreV1Api()
    
    print(f"Waiting for DNS chaos pods to complete (up to {duration_seconds} seconds)...")
    end_time = time.time() + duration_seconds + 30  # Add buffer time
    
    while time.time() < end_time:
        all_completed = True
        for pod_name in created_resources["chaos_pods"]:
            try:
                pod = k8s_client.read_namespaced_pod(pod_name, namespace)
                if pod.status.phase not in ["Succeeded", "Failed"]:
                    all_completed = False
                    break
            except kubernetes.client.rest.ApiException:
                # Pod might have been deleted
                continue
        
        if all_completed:
            print("All DNS chaos pods have completed")
            break
        
        time.sleep(10)
        print(".", end="", flush=True)
    
    print("\nDNS issue scenario completed")
    return created_resources

def cleanup_resources(namespace, resources):
    """Clean up all created resources"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    # Delete pods first
    for pod_name in resources["chaos_pods"] + resources["consumer_pods"]:
        try:
            k8s_client.delete_namespaced_pod(pod_name, namespace)
            print(f"Deleted pod {pod_name}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting pod {pod_name}: {e}")
    
    # Delete services
    for service_name in resources["services"]:
        try:
            k8s_client.delete_namespaced_service(service_name, namespace)
            print(f"Deleted service {service_name}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting service {service_name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate DNS resolution issues in a Kubernetes cluster")
    parser.add_argument("--namespace", default="default", help="Namespace to create resources in")
    parser.add_argument("--pods", type=int, default=5, help="Number of consumer pods to create")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of DNS issues")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--cleanup", action="store_true", help="Clean up resources after completion")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    kubernetes.config.load_kube_config()
    
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Starting DNS issues simulation with pattern '{args.pattern}' for {args.duration} seconds")
    
    resources = run_dns_issue_scenario(args.namespace, args.pods, args.duration, args.pattern)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"DNS issues simulation completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    
    # Print summary of created resources
    print("\nCreated resources:")
    for res_type, res_list in resources.items():
        print(f"- {res_type}: {len(res_list)}")
    
    if args.cleanup:
        print("\nCleaning up resources...")
        cleanup_resources(args.namespace, resources) 