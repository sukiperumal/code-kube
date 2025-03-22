import argparse
import kubernetes.client
import kubernetes.config
import time
import random
import uuid
import threading
import sys
import signal
from datetime import datetime

# Global flag to stop threads
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    """Handle Ctrl+C to stop threads gracefully"""
    print("\nStopping API pressure test...")
    shutdown_event.set()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def generate_large_configmap(namespace, name, size_kb=1024):
    """Generate a ConfigMap with a large amount of data to stress etcd"""
    # Create a large random string of specified size
    data = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=size_kb * 1024))
    
    # Break it into chunks to avoid hitting API limits
    chunk_size = 800 * 1024  # 800KB chunks
    data_chunks = {}
    
    for i in range(0, len(data), chunk_size):
        end = min(i + chunk_size, len(data))
        chunk_key = f"data-chunk-{i // chunk_size}"
        data_chunks[chunk_key] = data[i:end]
    
    # Create ConfigMap
    k8s_client = kubernetes.client.CoreV1Api()
    config_map = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": "control-plane-stress",
                "scenario": "control-plane-issues"
            }
        },
        "data": data_chunks
    }
    
    try:
        k8s_client.create_namespaced_config_map(namespace, config_map)
        print(f"Created large ConfigMap '{name}' ({size_kb}KB) in namespace {namespace}")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating ConfigMap: {e}")
        return None

def bombard_api_server(threads=10, requests_per_second=5, duration_seconds=60):
    """Create a load on the API server by making many list requests"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    def worker():
        request_count = 0
        start_time = time.time()
        
        while not shutdown_event.is_set() and time.time() - start_time < duration_seconds:
            try:
                # Make API requests that are relatively heavy
                k8s_client.list_pod_for_all_namespaces(watch=False)
                k8s_client.list_service_for_all_namespaces(watch=False)
                k8s_client.list_endpoints_for_all_namespaces(watch=False)
                
                request_count += 3
                
                # Sleep to control request rate
                time.sleep(1.0 / requests_per_second)
            except Exception as e:
                print(f"Error making API request: {e}")
                time.sleep(1)  # Back off on errors
        
        print(f"Worker completed, made {request_count} requests")
    
    print(f"Starting API load test with {threads} threads, {requests_per_second} requests/sec per thread...")
    thread_list = []
    
    for i in range(threads):
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        thread_list.append(t)
        
        # Stagger thread starts to avoid immediate burst
        time.sleep(0.5)
    
    # Wait for threads to complete
    end_time = time.time() + duration_seconds
    while time.time() < end_time and not shutdown_event.is_set():
        alive_threads = sum(1 for t in thread_list if t.is_alive())
        print(f"API load test running... {alive_threads} active threads, {int(end_time - time.time())}s remaining")
        time.sleep(5)
    
    # Signal threads to stop
    shutdown_event.set()
    
    # Wait for threads to finish
    for t in thread_list:
        t.join(timeout=5)
    
    print("API load test complete")

def create_etcd_stress_test(namespace, num_configmaps=10, size_kb=1024):
    """Create a number of large ConfigMaps to stress etcd"""
    created_resources = []
    
    for i in range(num_configmaps):
        timestamp = int(time.time())
        uid = str(uuid.uuid4())[:5]
        name = f"etcd-stress-{timestamp}-{i}-{uid}"
        
        # Random size between 50% and 150% of specified size
        actual_size = int(size_kb * random.uniform(0.5, 1.5))
        
        if generate_large_configmap(namespace, name, actual_size):
            created_resources.append(name)
    
    return created_resources

def create_watch_bombardment(namespace, duration_seconds=300):
    """Create many watch requests to stress the API server and etcd"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    def watch_worker(resource_type):
        try:
            w = kubernetes.watch.Watch()
            
            # Set up watch based on resource type
            if resource_type == "pods":
                stream = w.stream(k8s_client.list_pod_for_all_namespaces, timeout_seconds=duration_seconds)
            elif resource_type == "services":
                stream = w.stream(k8s_client.list_service_for_all_namespaces, timeout_seconds=duration_seconds)
            elif resource_type == "configmaps":
                stream = w.stream(k8s_client.list_config_map_for_all_namespaces, timeout_seconds=duration_seconds)
            elif resource_type == "events":
                stream = w.stream(k8s_client.list_event_for_all_namespaces, timeout_seconds=duration_seconds)
            else:
                print(f"Unknown resource type: {resource_type}")
                return
            
            print(f"Started watch on {resource_type}")
            
            # Process events from the watch
            for event in stream:
                if shutdown_event.is_set():
                    break
                # Just drain the events without processing to keep the watch active
            
            print(f"Watch on {resource_type} completed")
            
        except Exception as e:
            print(f"Error in watch for {resource_type}: {e}")
    
    resource_types = ["pods", "services", "configmaps", "events"]
    thread_list = []
    
    # Create watches for multiple resource types
    for res_type in resource_types:
        for i in range(3):  # 3 watches per resource type
            t = threading.Thread(target=watch_worker, args=(res_type,))
            t.daemon = True
            t.start()
            thread_list.append(t)
            time.sleep(0.5)  # Stagger starts
    
    print(f"Started {len(thread_list)} watch threads")
    
    # Wait for the specified duration
    end_time = time.time() + duration_seconds
    while time.time() < end_time and not shutdown_event.is_set():
        alive_threads = sum(1 for t in thread_list if t.is_alive())
        print(f"Watch bombardment running... {alive_threads} active watches, {int(end_time - time.time())}s remaining")
        time.sleep(10)
    
    # Signal threads to stop
    shutdown_event.set()
    
    # Wait for threads to finish
    for t in thread_list:
        t.join(timeout=5)
    
    print("Watch bombardment complete")

def run_control_plane_scenario(namespace, num_resources, duration_seconds, pattern="random"):
    """Run a scenario to stress control plane components"""
    created_resources = []
    
    if pattern == "random":
        # Mix of etcd stress and API server stress
        
        # Create some large ConfigMaps to stress etcd
        num_configmaps = random.randint(5, num_resources)
        print(f"Creating {num_configmaps} large ConfigMaps to stress etcd...")
        created_resources.extend(create_etcd_stress_test(namespace, num_configmaps, size_kb=1024))
        
        # Run API server bombardment for a portion of the time
        api_duration = min(duration_seconds - 30, 120)  # Cap at 2 minutes but leave time for cleanup
        threads = random.randint(5, 15)
        requests_per_second = random.randint(2, 8)
        
        print(f"Running API server load test with {threads} threads for {api_duration} seconds...")
        shutdown_event.clear()  # Reset shutdown flag
        bombard_api_server(threads, requests_per_second, api_duration)
        
        # Run watch bombardment for a portion of the time
        watch_duration = min(duration_seconds - 30, 180)  # Cap at 3 minutes but leave time for cleanup
        print(f"Running watch bombardment for {watch_duration} seconds...")
        shutdown_event.clear()  # Reset shutdown flag
        create_watch_bombardment(namespace, watch_duration)
    
    elif pattern == "gradual":
        # Gradually increase pressure on control plane
        
        # Start with a few ConfigMaps
        initial_configmaps = max(1, num_resources // 5)
        print(f"Creating initial {initial_configmaps} ConfigMaps...")
        created_resources.extend(create_etcd_stress_test(namespace, initial_configmaps, size_kb=512))
        
        # Run light API server load
        print(f"Running light API server load...")
        shutdown_event.clear()
        bombard_api_server(threads=3, requests_per_second=2, duration_seconds=min(30, duration_seconds // 4))
        
        # Add more ConfigMaps
        middle_configmaps = max(2, num_resources // 3)
        print(f"Adding {middle_configmaps} more ConfigMaps...")
        created_resources.extend(create_etcd_stress_test(namespace, middle_configmaps, size_kb=1024))
        
        # Run medium API server load
        print(f"Running medium API server load...")
        shutdown_event.clear()
        bombard_api_server(threads=7, requests_per_second=5, duration_seconds=min(60, duration_seconds // 3))
        
        # Add final batch of ConfigMaps
        final_configmaps = max(3, num_resources // 2)
        print(f"Adding final {final_configmaps} ConfigMaps...")
        created_resources.extend(create_etcd_stress_test(namespace, final_configmaps, size_kb=2048))
        
        # Run heavy watch bombardment
        watch_duration = min(duration_seconds - 120, 120)  # Cap at 2 minutes but leave time
        if watch_duration > 0:
            print(f"Running watch bombardment for {watch_duration} seconds...")
            shutdown_event.clear()
            create_watch_bombardment(namespace, watch_duration)
    
    elif pattern == "spike":
        # Sudden spike in control plane load
        
        # Create a large number of ConfigMaps quickly
        large_configmap_count = num_resources * 2
        print(f"Creating spike of {large_configmap_count} large ConfigMaps...")
        created_resources.extend(create_etcd_stress_test(namespace, large_configmap_count, size_kb=2048))
        
        # Run intense API bombardment
        api_duration = min(duration_seconds - 60, 90)  # Cap at 90 seconds but leave time
        print(f"Running intense API server load test for {api_duration} seconds...")
        shutdown_event.clear()
        bombard_api_server(threads=20, requests_per_second=10, duration_seconds=api_duration)
        
        # Run intense watch bombardment in parallel
        watch_duration = min(duration_seconds - 30, 120)  # Cap at 2 minutes but leave time
        if watch_duration > 0:
            print(f"Running intense watch bombardment for {watch_duration} seconds...")
            shutdown_event.clear()
            create_watch_bombardment(namespace, watch_duration)
    
    else:
        print(f"Unknown pattern: {pattern}")
        return created_resources
    
    # Check if we need to wait more
    remaining_time = duration_seconds - (time.time() - int(created_resources[0].split('-')[2]) if created_resources else 0)
    if remaining_time > 0:
        print(f"Waiting for {int(remaining_time)} more seconds...")
        time.sleep(remaining_time)
    
    return created_resources

def cleanup_resources(namespace, resources):
    """Clean up the ConfigMaps created during the test"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    for resource_name in resources:
        try:
            k8s_client.delete_namespaced_config_map(resource_name, namespace)
            print(f"Deleted ConfigMap {resource_name}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting ConfigMap {resource_name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate control plane issues in a Kubernetes cluster")
    parser.add_argument("--namespace", default="default", help="Namespace to create resources in")
    parser.add_argument("--pods", type=int, default=5, help="Number of resources to create (approximation)")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of control plane stress")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--cleanup", action="store_true", help="Clean up resources after completion")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    kubernetes.config.load_kube_config()
    
    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Starting control plane issues simulation with pattern '{args.pattern}' for {args.duration} seconds")
    
    resources = run_control_plane_scenario(args.namespace, args.pods, args.duration, args.pattern)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Control plane issues simulation completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    print(f"Created {len(resources)} resources")
    
    if args.cleanup:
        print("\nCleaning up resources...")
        cleanup_resources(args.namespace, resources) 