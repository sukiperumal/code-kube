#!/usr/bin/env python3
import argparse
import os
import time
import subprocess
import pandas as pd
from datetime import datetime

def run_simulation(scenario_type, namespace, duration, pods, pattern, cleanup=True):
    """Run a specific simulation scenario."""
    script = None
    args = []
    
    if scenario_type == "resource":
        script = "src/simulation/resource_exhaustion.py"
        args = [
            "--namespace", namespace,
            "--duration", str(duration),
            "--pods", str(pods),
            "--pattern", pattern
        ]
    elif scenario_type == "network":
        script = "src/simulation/network_issues.py"
        args = [
            "--namespace", namespace,
            "--duration", str(duration),
            "--pods", str(pods),
            "--pattern", pattern
        ]
    elif scenario_type == "pod-failure":
        script = "src/simulation/pod_failures.py"
        args = [
            "--namespace", namespace,
            "--duration", str(duration),
            "--pods", str(pods),
            "--pattern", pattern
        ]
        if cleanup:
            args.append("--cleanup")
    
    if script:
        cmd = ["python3", script] + args
        print(f"Running command: {' '.join(cmd)}")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            print(f"Error running simulation: {stderr}")
            return False
        
        print(stdout)
        return True
    else:
        print(f"Unknown scenario type: {scenario_type}")
        return False

def collect_metrics(prometheus_url, duration, namespaces=None, process=True, cluster_issue_type=None):
    """Collect metrics from the cluster."""
    script = "src/data_collection/collector.py"
    
    args = [
        "--prometheus-url", prometheus_url,
        "--duration", str(duration)
    ]
    
    if namespaces:
        args.extend(["--namespaces"] + namespaces)
    
    if process:
        args.append("--process")
    
    if cluster_issue_type:
        args.extend(["--cluster-issue-type", cluster_issue_type])
    
    cmd = ["python3", script] + args
    print(f"Running command: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        print(f"Error collecting metrics: {stderr}")
        return None
    
    print(stdout)
    
    # Extract the processed file path from stdout
    for line in stdout.split('\n'):
        if "Saved processed metrics to" in line:
            return line.split("Saved processed metrics to")[-1].strip()
    
    return None

def train_model(data_file, model_dir="models"):
    """Train the ML models using collected data."""
    script = "src/models/predictor.py"
    
    args = [
        "--data", data_file,
        "--mode", "train",
        "--model-dir", model_dir
    ]
    
    cmd = ["python3", script] + args
    print(f"Running command: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        print(f"Error training model: {stderr}")
        return False
    
    print(stdout)
    return True

def predict(data_file, model_dir="models"):
    """Make predictions using trained models."""
    script = "src/models/predictor.py"
    
    args = [
        "--data", data_file,
        "--mode", "predict",
        "--model-dir", model_dir
    ]
    
    cmd = ["python3", script] + args
    print(f"Running command: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        print(f"Error making predictions: {stderr}")
        return None
    
    print(stdout)
    
    # Extract the prediction results file path
    for line in stdout.split('\n'):
        if "Predictions saved to" in line:
            return line.split("Predictions saved to")[-1].strip()
    
    return None

def run_complete_workflow(scenarios, namespace, duration, pods, prometheus_url, 
                         model_dir="models", train_after=True, predict_after=True):
    """Run a complete workflow with multiple scenarios, data collection, and model training/prediction."""
    # Ensure the namespace exists
    os.system(f"kubectl create namespace {namespace} --dry-run=client -o yaml | kubectl apply -f -")
    
    # Run each scenario
    for scenario in scenarios:
        print(f"\n{'='*80}\nRunning {scenario} scenario\n{'='*80}")
        success = run_simulation(
            scenario_type=scenario,
            namespace=namespace,
            duration=duration,
            pods=pods,
            pattern="random",
            cleanup=True
        )
        
        if not success:
            print(f"Failed to run {scenario} scenario, skipping...")
            continue
        
        # Collect metrics after each scenario
        print(f"\n{'='*80}\nCollecting metrics after {scenario} scenario\n{'='*80}")
        data_file = collect_metrics(
            prometheus_url=prometheus_url,
            duration=duration // 60 + 1,  # Convert seconds to minutes
            namespaces=[namespace, "monitoring", "kube-system"],
            process=True,
            cluster_issue_type=scenario  # Pass the scenario type as the cluster issue type
        )
        
        if not data_file:
            print(f"Failed to collect metrics after {scenario} scenario, skipping...")
            continue
        
        # Train model if requested
        if train_after:
            print(f"\n{'='*80}\nTraining model after {scenario} scenario\n{'='*80}")
            success = train_model(data_file, model_dir)
            
            if not success:
                print(f"Failed to train model after {scenario} scenario")
        
        # Make predictions if requested
        if predict_after:
            print(f"\n{'='*80}\nMaking predictions after {scenario} scenario\n{'='*80}")
            prediction_file = predict(data_file, model_dir)
            
            if not prediction_file:
                print(f"Failed to make predictions after {scenario} scenario")
            else:
                # Display predictions
                try:
                    predictions = pd.read_csv(prediction_file)
                    print("\nPrediction Results:")
                    print(predictions.head(10))
                except Exception as e:
                    print(f"Error reading prediction results: {e}")
        
        # Wait a bit before the next scenario
        print(f"Waiting 30 seconds before the next scenario...")
        time.sleep(30)
    
    print("\nWorkflow completed!")

def main():
    parser = argparse.ArgumentParser(description="Run Kubernetes issue prediction workflow")
    parser.add_argument("--mode", choices=["simulate", "collect", "train", "predict", "workflow"], 
                       required=True, help="Mode of operation")
    parser.add_argument("--scenario", choices=["resource", "network", "pod-failure"], 
                       help="Simulation scenario type (for simulate mode)")
    parser.add_argument("--namespace", default="ml-scenarios", 
                       help="Kubernetes namespace to use")
    parser.add_argument("--duration", type=int, default=300, 
                       help="Duration of simulation in seconds")
    parser.add_argument("--pods", type=int, default=5, 
                       help="Number of pods to create for simulation")
    parser.add_argument("--pattern", choices=["random", "gradual", "spike"], default="random", 
                       help="Pattern of simulation")
    parser.add_argument("--prometheus-url", default="http://prometheus-server.monitoring.svc.cluster.local:9090", 
                       help="URL of the Prometheus server")
    parser.add_argument("--data", help="Path to data file (for train/predict modes)")
    parser.add_argument("--model-dir", default="models", 
                       help="Directory for saving/loading models")
    
    args = parser.parse_args()
    
    if args.mode == "simulate":
        if not args.scenario:
            parser.error("--scenario is required for simulate mode")
        
        run_simulation(
            scenario_type=args.scenario,
            namespace=args.namespace,
            duration=args.duration,
            pods=args.pods,
            pattern=args.pattern,
            cleanup=True
        )
    
    elif args.mode == "collect":
        collect_metrics(
            prometheus_url=args.prometheus_url,
            duration=args.duration // 60 + 1,  # Convert seconds to minutes
            namespaces=[args.namespace, "monitoring", "kube-system"],
            process=True
        )
    
    elif args.mode == "train":
        if not args.data:
            parser.error("--data is required for train mode")
        
        train_model(args.data, args.model_dir)
    
    elif args.mode == "predict":
        if not args.data:
            parser.error("--data is required for predict mode")
        
        predict(args.data, args.model_dir)
    
    elif args.mode == "workflow":
        run_complete_workflow(
            scenarios=["resource", "network", "pod-failure"],
            namespace=args.namespace,
            duration=args.duration,
            pods=args.pods,
            prometheus_url=args.prometheus_url,
            model_dir=args.model_dir,
            train_after=True,
            predict_after=True
        )

if __name__ == "__main__":
    main() 