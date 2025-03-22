#!/usr/bin/env python3
import argparse
import os
import time
import subprocess
import pandas as pd
import random
from datetime import datetime
import glob
import requests
import sys

def check_prometheus_connection(prometheus_url):
    """Check if the Prometheus server is accessible."""
    try:
        response = requests.get(f"{prometheus_url}/api/v1/status/config", timeout=10)
        response.raise_for_status()
        print(f"✅ Successfully connected to Prometheus at {prometheus_url}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to connect to Prometheus at {prometheus_url}")
        print(f"Error: {e}")
        print("\nTroubleshooting tips:")
        print("1. Check if the Prometheus server is running")
        print("2. Verify the URL is correct (including http:// prefix)")
        print("3. Try using localhost or IP address instead of DNS name")
        print("4. Ensure network connectivity and firewall rules allow the connection")
        return False

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
    elif scenario_type == "none":
        # For baseline/normal operation data collection
        # Just wait for the duration
        print(f"Collecting baseline data for {duration} seconds...")
        time.sleep(duration)
        return True
    
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
    # Verify Prometheus connection before proceeding
    if not check_prometheus_connection(prometheus_url):
        print("Cannot collect metrics without Prometheus connection.")
        return None
        
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

def generate_datasets(data_dir="data/processed", output_dir="data/datasets", test_split=0.2):
    """
    Combine all processed data files into training and testing datasets.
    
    Args:
        data_dir: Directory containing processed metric CSV files
        output_dir: Directory to save the combined datasets
        test_split: Fraction of data to use for testing (0.0 to 1.0)
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Get all processed CSV files
    csv_files = glob.glob(f"{data_dir}/processed_metrics_*.csv")
    
    if not csv_files:
        print(f"No processed metric files found in {data_dir}")
        return
    
    print(f"Found {len(csv_files)} processed metric files")
    
    # Combine all files into one DataFrame
    all_data = []
    for file in csv_files:
        df = pd.read_csv(file, parse_dates=True, index_col=0)
        all_data.append(df)
    
    combined_df = pd.concat(all_data, axis=0)
    
    # Shuffle the data
    combined_df = combined_df.sample(frac=1.0, random_state=42)
    
    # Split into training and testing
    test_size = int(len(combined_df) * test_split)
    train_df = combined_df.iloc[test_size:]
    test_df = combined_df.iloc[:test_size]
    
    # Save to files
    timestamp = datetime.now().strftime("%Y%m%d")
    train_file = f"{output_dir}/training_data_{timestamp}.csv"
    test_file = f"{output_dir}/testing_data_{timestamp}.csv"
    
    train_df.to_csv(train_file)
    test_df.to_csv(test_file)
    
    print(f"Saved training data ({len(train_df)} rows) to {train_file}")
    print(f"Saved testing data ({len(test_df)} rows) to {test_file}")
    
    # Print dataset statistics
    print("\nDataset Statistics:")
    issue_counts = combined_df['cluster_issue_type'].value_counts()
    for issue_type, count in issue_counts.items():
        print(f"  {issue_type}: {count} samples ({count/len(combined_df)*100:.1f}%)")
    
    return train_file, test_file

def collect_scenario_data(scenario_type, namespace, prometheus_url, 
                         iterations=3, duration_range=(180, 300), pods_range=(3, 10),
                         patterns=None):
    """
    Collect metrics data for a specific scenario type with variations.
    
    Args:
        scenario_type: Type of scenario to simulate (resource, network, pod-failure, none)
        namespace: Kubernetes namespace to use
        prometheus_url: URL of the Prometheus server
        iterations: Number of iterations to run for this scenario
        duration_range: Range of durations (min, max) in seconds
        pods_range: Range of pod counts (min, max)
        patterns: List of patterns to use (random, gradual, spike)
    """
    if patterns is None:
        patterns = ["random", "gradual", "spike"]
    
    data_files = []
    
    for i in range(iterations):
        # Randomly select parameters for variation
        duration = random.randint(duration_range[0], duration_range[1])
        pods = random.randint(pods_range[0], pods_range[1])
        pattern = random.choice(patterns)
        
        print(f"\n{'='*80}")
        print(f"Running {scenario_type} scenario - Iteration {i+1}/{iterations}")
        print(f"Parameters: duration={duration}s, pods={pods}, pattern={pattern}")
        print(f"{'='*80}")
        
        # Run simulation
        success = run_simulation(
            scenario_type=scenario_type,
            namespace=namespace,
            duration=duration,
            pods=pods,
            pattern=pattern,
            cleanup=True
        )
        
        if not success and scenario_type != "none":
            print(f"Failed to run {scenario_type} scenario, skipping...")
            continue
        
        # Collect metrics
        data_file = collect_metrics(
            prometheus_url=prometheus_url,
            duration=duration // 60 + 1,  # Convert seconds to minutes
            namespaces=[namespace, "monitoring", "kube-system"],
            process=True,
            cluster_issue_type=scenario_type
        )
        
        if data_file:
            data_files.append(data_file)
            print(f"Successfully collected data for {scenario_type} scenario (iteration {i+1})")
        else:
            print(f"Failed to collect metrics for {scenario_type} scenario (iteration {i+1})")
        
        # Wait between iterations
        wait_time = random.randint(30, 60)
        print(f"Waiting {wait_time} seconds before next iteration...")
        time.sleep(wait_time)
    
    return data_files

def main():
    parser = argparse.ArgumentParser(description="Collect Kubernetes cluster issue data for ML")
    parser.add_argument("--namespace", default="ml-scenarios", help="Kubernetes namespace to use")
    parser.add_argument("--prometheus-url", default="http://prometheus-server.monitoring.svc.cluster.local:9090", 
                        help="URL of the Prometheus server")
    parser.add_argument("--iterations", type=int, default=3, 
                        help="Number of iterations per scenario type")
    parser.add_argument("--output-dir", default="data/datasets", 
                        help="Directory to save the combined datasets")
    parser.add_argument("--scenarios", nargs="+", 
                        choices=["resource", "network", "pod-failure", "none"], 
                        default=["resource", "network", "pod-failure", "none"],
                        help="Scenario types to collect data for")
    parser.add_argument("--skip-combine", action="store_true", 
                        help="Skip combining data into training/testing datasets")
    parser.add_argument("--check-connection-only", action="store_true",
                        help="Only check Prometheus connection and exit")
    
    args = parser.parse_args()
    
    # Check if Prometheus is reachable
    if args.check_connection_only:
        sys.exit(0 if check_prometheus_connection(args.prometheus_url) else 1)
    
    # Verify Prometheus connection before proceeding with the full workflow
    if not check_prometheus_connection(args.prometheus_url):
        print("\nERROR: Cannot connect to Prometheus. Please check your connection and try again.")
        print("You can use the --prometheus-url parameter to specify a different Prometheus URL.")
        print("Example: --prometheus-url http://localhost:9090")
        sys.exit(1)
    
    # Ensure the namespace exists
    os.system(f"kubectl create namespace {args.namespace} --dry-run=client -o yaml | kubectl apply -f -")
    
    # Collect data for each scenario type
    all_data_files = []
    
    for scenario in args.scenarios:
        data_files = collect_scenario_data(
            scenario_type=scenario,
            namespace=args.namespace,
            prometheus_url=args.prometheus_url,
            iterations=args.iterations
        )
        all_data_files.extend(data_files)
    
    print(f"\nTotal data files collected: {len(all_data_files)}")
    
    # Combine data into training and testing datasets
    if not args.skip_combine and all_data_files:
        train_file, test_file = generate_datasets(output_dir=args.output_dir)
        print(f"\nDataset generation complete.")
    
if __name__ == "__main__":
    main() 