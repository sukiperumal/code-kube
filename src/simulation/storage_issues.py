import argparse
import kubernetes.client
import kubernetes.config
import time
import random
import uuid
import sys
from datetime import datetime

def create_problematic_pv(name, namespace, size_gi=1, reclaim_policy="Delete", access_mode="ReadWriteOnce"):
    """
    Create a PersistentVolume that will have issues
    Uses a hostPath that doesn't exist or has permission problems
    """
    k8s_client = kubernetes.client.CoreV1Api()
    
    # Generate a random path that likely doesn't exist
    problematic_host_path = f"/mnt/problematic-storage-{uuid.uuid4()}"
    
    pv = {
        "apiVersion": "v1",
        "kind": "PersistentVolume",
        "metadata": {
            "name": name,
            "labels": {
                "type": "problematic-storage",
                "scenario": "storage-issues"
            }
        },
        "spec": {
            "capacity": {
                "storage": f"{size_gi}Gi"
            },
            "accessModes": [access_mode],
            "persistentVolumeReclaimPolicy": reclaim_policy,
            "hostPath": {
                "path": problematic_host_path
            }
        }
    }
    
    try:
        k8s_client.create_persistent_volume(pv)
        print(f"Created problematic PV '{name}' with hostPath {problematic_host_path}")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating PV: {e}")
        return None

def create_problematic_storageclass(name, provisioner="kubernetes.io/no-provisioner"):
    """
    Create a StorageClass that will have provisioning issues
    Uses a nonexistent or misconfigured provisioner
    """
    k8s_client = kubernetes.client.StorageV1Api()
    
    storage_class = {
        "apiVersion": "storage.k8s.io/v1",
        "kind": "StorageClass",
        "metadata": {
            "name": name,
            "labels": {
                "type": "problematic-storage",
                "scenario": "storage-issues"
            }
        },
        "provisioner": provisioner,
        "reclaimPolicy": "Delete",
        "volumeBindingMode": "Immediate",
        "parameters": {
            "error-rate": "0.8",  # Parameter that would cause provisioner to fail 80% of the time
            "delay-seconds": "30"  # Parameter that would cause provisioner to be slow
        }
    }
    
    try:
        k8s_client.create_storage_class(storage_class)
        print(f"Created problematic StorageClass '{name}' with provisioner {provisioner}")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating StorageClass: {e}")
        return None

def create_pvc(name, namespace, storage_class_name=None, pv_name=None, size_gi=1, access_mode="ReadWriteOnce"):
    """Create a PVC that will try to bind to the problematic storage"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "type": "problematic-storage",
                "scenario": "storage-issues"
            }
        },
        "spec": {
            "accessModes": [access_mode],
            "resources": {
                "requests": {
                    "storage": f"{size_gi}Gi"
                }
            }
        }
    }
    
    if storage_class_name:
        pvc["spec"]["storageClassName"] = storage_class_name
    
    if pv_name:
        # Selectors can be used to target specific PVs
        pvc["spec"]["selector"] = {
            "matchLabels": {
                "type": "problematic-storage"
            }
        }
    
    try:
        k8s_client.create_namespaced_persistent_volume_claim(namespace, pvc)
        print(f"Created PVC '{name}' in namespace {namespace}")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating PVC: {e}")
        return None

def create_pod_with_pvc(name, namespace, pvc_name, image="busybox"):
    """Create a pod that tries to use the problematic PVC"""
    k8s_client = kubernetes.client.CoreV1Api()
    
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": "storage-test",
                "scenario": "storage-issues"
            }
        },
        "spec": {
            "containers": [{
                "name": "test-container",
                "image": image,
                "command": ["sh", "-c", "while true; do echo 'Trying to write to volume' > /data/test; sleep 5; done"],
                "volumeMounts": [{
                    "name": "data-volume",
                    "mountPath": "/data"
                }]
            }],
            "volumes": [{
                "name": "data-volume",
                "persistentVolumeClaim": {
                    "claimName": pvc_name
                }
            }]
        }
    }
    
    try:
        k8s_client.create_namespaced_pod(namespace, pod)
        print(f"Created pod '{name}' using PVC '{pvc_name}' in namespace {namespace}")
        return name
    except kubernetes.client.rest.ApiException as e:
        print(f"Error creating pod: {e}")
        return None

def run_storage_failure_scenario(namespace, num_resources, duration_seconds, pattern="random"):
    """Run a scenario with storage failures"""
    created_resources = {
        "pvs": [],
        "pvcs": [],
        "storage_classes": [],
        "pods": []
    }
    
    # Generate unique IDs for resources
    timestamp = int(time.time())
    uid = str(uuid.uuid4())[:5]
    
    if pattern == "random":
        # Create a mix of problematic storage resources
        
        # Create some problematic PVs
        for i in range(num_resources):
            pv_name = f"pv-problematic-{timestamp}-{i}-{uid}"
            if create_problematic_pv(pv_name, namespace, size_gi=random.randint(1, 5)):
                created_resources["pvs"].append(pv_name)
        
        # Create a problematic StorageClass
        sc_name = f"sc-problematic-{timestamp}-{uid}"
        if create_problematic_storageclass(sc_name):
            created_resources["storage_classes"].append(sc_name)
        
        # Create PVCs that will try to use problematic storage
        for i in range(num_resources):
            pvc_name = f"pvc-problematic-{timestamp}-{i}-{uid}"
            
            # Randomly choose between using SC or PV selector
            if random.choice([True, False]) and created_resources["storage_classes"]:
                # Use problematic StorageClass
                if create_pvc(pvc_name, namespace, storage_class_name=sc_name):
                    created_resources["pvcs"].append(pvc_name)
            elif created_resources["pvs"]:
                # Use selector for problematic PV
                if create_pvc(pvc_name, namespace, pv_name=random.choice(created_resources["pvs"])):
                    created_resources["pvcs"].append(pvc_name)
        
        # Create pods that will try to use the problematic PVCs
        for pvc_name in created_resources["pvcs"]:
            pod_name = f"pod-storage-test-{timestamp}-{uid}-{pvc_name}"
            if create_pod_with_pvc(pod_name, namespace, pvc_name):
                created_resources["pods"].append(pod_name)
    
    elif pattern == "gradual":
        # Start with one storage issue and gradually add more
        # First create the basic problematic components
        pv_name = f"pv-problematic-{timestamp}-0-{uid}"
        if create_problematic_pv(pv_name, namespace):
            created_resources["pvs"].append(pv_name)
            
        sc_name = f"sc-problematic-{timestamp}-{uid}"
        if create_problematic_storageclass(sc_name):
            created_resources["storage_classes"].append(sc_name)
            
        # Create initial PVC and pod
        if created_resources["pvs"]:
            pvc_name = f"pvc-problematic-{timestamp}-0-{uid}"
            if create_pvc(pvc_name, namespace, pv_name=pv_name):
                created_resources["pvcs"].append(pvc_name)
                
                pod_name = f"pod-storage-test-{timestamp}-{uid}-{pvc_name}"
                if create_pod_with_pvc(pod_name, namespace, pvc_name):
                    created_resources["pods"].append(pod_name)
        
        # Schedule additional storage components over time
        delay_per_resource = duration_seconds / (num_resources * 2)
        
        for i in range(1, num_resources):
            # Sleep before adding more resources
            time.sleep(delay_per_resource)
            
            # Add a new problematic PV
            pv_name = f"pv-problematic-{timestamp}-{i}-{uid}"
            if create_problematic_pv(pv_name, namespace):
                created_resources["pvs"].append(pv_name)
            
            # Add a PVC for it
            pvc_name = f"pvc-problematic-{timestamp}-{i}-{uid}"
            if create_pvc(pvc_name, namespace, pv_name=pv_name):
                created_resources["pvcs"].append(pvc_name)
                
                # And a pod using that PVC
                pod_name = f"pod-storage-test-{timestamp}-{uid}-{pvc_name}"
                if create_pod_with_pvc(pod_name, namespace, pvc_name):
                    created_resources["pods"].append(pod_name)
                    
            # Periodically create PVCs with the problematic StorageClass too
            if i % 2 == 0 and created_resources["storage_classes"]:
                sc_pvc_name = f"pvc-sc-problematic-{timestamp}-{i}-{uid}"
                if create_pvc(sc_pvc_name, namespace, storage_class_name=sc_name):
                    created_resources["pvcs"].append(sc_pvc_name)
                    
                    pod_name = f"pod-storage-test-sc-{timestamp}-{uid}-{sc_pvc_name}"
                    if create_pod_with_pvc(pod_name, namespace, sc_pvc_name):
                        created_resources["pods"].append(pod_name)
    
    elif pattern == "spike":
        # Create a sudden spike of storage issues
        # Create many problematic storage components at once
        
        # Create problematic Storage Class
        sc_name = f"sc-problematic-{timestamp}-{uid}"
        if create_problematic_storageclass(sc_name):
            created_resources["storage_classes"].append(sc_name)
        
        # Create more PVs than requested for a spike
        for i in range(num_resources * 2):
            pv_name = f"pv-problematic-{timestamp}-{i}-{uid}"
            if create_problematic_pv(pv_name, namespace):
                created_resources["pvs"].append(pv_name)
        
        # Create a lot of PVCs at once
        for i in range(num_resources * 3):
            pvc_name = f"pvc-problematic-{timestamp}-{i}-{uid}"
            
            # Mix of StorageClass and PV-selector PVCs
            if i % 3 == 0 and created_resources["storage_classes"]:
                if create_pvc(pvc_name, namespace, storage_class_name=sc_name):
                    created_resources["pvcs"].append(pvc_name)
            elif created_resources["pvs"]:
                if create_pvc(pvc_name, namespace, pv_name=random.choice(created_resources["pvs"])):
                    created_resources["pvcs"].append(pvc_name)
        
        # Create a burst of pods using the PVCs
        for pvc_name in created_resources["pvcs"]:
            pod_name = f"pod-storage-test-{timestamp}-{uid}-{len(created_resources['pods'])}"
            if create_pod_with_pvc(pod_name, namespace, pvc_name):
                created_resources["pods"].append(pod_name)
            
            # Create some pods with slightly different configs
            if random.random() < 0.3:  # 30% of the time
                pod_name = f"pod-storage-test-alt-{timestamp}-{uid}-{len(created_resources['pods'])}"
                if create_pod_with_pvc(pod_name, namespace, pvc_name, image="nginx:alpine"):
                    created_resources["pods"].append(pod_name)
    
    else:
        print(f"Unknown pattern: {pattern}")
        return created_resources
    
    # If we need to wait more, sleep
    remaining_time = duration_seconds - (time.time() - timestamp)
    if remaining_time > 0:
        print(f"Waiting for {int(remaining_time)} more seconds...")
        time.sleep(remaining_time)
    
    return created_resources

def cleanup_resources(namespace, resources):
    """Clean up all created resources"""
    k8s_core = kubernetes.client.CoreV1Api()
    k8s_storage = kubernetes.client.StorageV1Api()
    
    # Delete pods first
    for pod_name in resources["pods"]:
        try:
            k8s_core.delete_namespaced_pod(pod_name, namespace)
            print(f"Deleted pod {pod_name}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting pod {pod_name}: {e}")
    
    # Delete PVCs next
    for pvc_name in resources["pvcs"]:
        try:
            k8s_core.delete_namespaced_persistent_volume_claim(pvc_name, namespace)
            print(f"Deleted PVC {pvc_name}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting PVC {pvc_name}: {e}")
    
    # Delete PVs
    for pv_name in resources["pvs"]:
        try:
            k8s_core.delete_persistent_volume(pv_name)
            print(f"Deleted PV {pv_name}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting PV {pv_name}: {e}")
    
    # Delete StorageClasses
    for sc_name in resources["storage_classes"]:
        try:
            k8s_storage.delete_storage_class(sc_name)
            print(f"Deleted StorageClass {sc_name}")
        except kubernetes.client.rest.ApiException as e:
            print(f"Error deleting StorageClass {sc_name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate storage issues in a Kubernetes cluster")
    parser.add_argument("--namespace", default="default", help="Namespace to create resources in")
    parser.add_argument("--pods", type=int, default=5, help="Number of resources to create (approximation)")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                        help="Pattern of storage issues")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--cleanup", action="store_true", help="Clean up resources after completion")
    
    args = parser.parse_args()
    
    # Load Kubernetes configuration from default location
    kubernetes.config.load_kube_config()
    
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Starting storage issues simulation with pattern '{args.pattern}' for {args.duration} seconds")
    
    resources = run_storage_failure_scenario(args.namespace, args.pods, args.duration, args.pattern)
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Storage issues simulation completed")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")
    
    # Print summary of created resources
    print("\nCreated resources:")
    for res_type, res_list in resources.items():
        print(f"- {res_type}: {len(res_list)}")
    
    if args.cleanup:
        print("\nCleaning up resources...")
        cleanup_resources(args.namespace, resources) 