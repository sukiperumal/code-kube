#!/usr/bin/env python3
import argparse
import sys
import time
import os
from datetime import datetime, timedelta
import json
from collector import KubernetesMetricsCollector

def main():
    """
    Command-line utility to collect enhanced Kubernetes metrics.
    This script collects all the standard and enhanced metrics defined in the pipeline.
    """
    parser = argparse.ArgumentParser(description="Collect enhanced metrics from a Kubernetes cluster")
    parser.add_argument("--prometheus-url", default="http://prometheus-server.monitoring.svc.cluster.local:9090", 
                       help="URL of the Prometheus server")
    parser.add_argument("--duration", type=int, default=30, 
                       help="Duration in minutes to collect metrics for")
    parser.add_argument("--step", default="15s", 
                       help="Step interval for Prometheus queries")
    parser.add_argument("--namespaces", nargs="+", default=["default", "kube-system", "monitoring"],
                       help="Namespaces to collect metrics from")
    parser.add_argument("--categories", nargs="+", 
                       help="Categories of metrics to collect (default: all)")
    parser.add_argument("--continuous", action="store_true",
                       help="Run in continuous mode, collecting metrics in intervals")
    parser.add_argument("--interval", type=int, default=60,
                       help="Interval in seconds between metric collections when in continuous mode")
    parser.add_argument("--output-dir", default="data/enhanced",
                       help="Directory to store output files")
    parser.add_argument("--cluster-issue", default=None,
                       help="Name of cluster issue being simulated (if any)")
    
    args = parser.parse_args()
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Initialize collector
    collector = KubernetesMetricsCollector(prometheus_url=args.prometheus_url)
    
    # Get available categories for help text
    available_categories = collector.METRICS_CATEGORIES
    
    if args.categories:
        # Validate categories
        for category in args.categories:
            if category not in available_categories and category != "all":
                print(f"Warning: Unknown category '{category}'. Available categories: {', '.join(available_categories)}")
        
        # Use specified categories
        categories = [cat for cat in args.categories if cat != "all"]
        if "all" in args.categories:
            categories = available_categories
    else:
        # Use all categories by default
        categories = available_categories
    
    if args.continuous:
        print(f"Starting continuous metrics collection every {args.interval} seconds...")
        print(f"Press Ctrl+C to stop collection")
        
        collection_count = 0
        try:
            while True:
                collection_count += 1
                print(f"\nCollection #{collection_count} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                metrics_result = collector.collect_metrics(
                    duration_minutes=args.duration,
                    step=args.step,
                    namespaces=args.namespaces,
                    cluster_issue_type=args.cluster_issue,
                    categories=categories
                )
                
                # Write summary of this collection
                print(f"Raw metrics saved to: {metrics_result['raw_file']}")
                print(f"Processed metrics saved to: {metrics_result['processed_file']}")
                
                # Wait for next interval
                print(f"Waiting {args.interval} seconds until next collection...")
                time.sleep(args.interval)
                
        except KeyboardInterrupt:
            print("\nMetrics collection stopped by user")
    else:
        # Single collection
        print(f"Collecting metrics for the past {args.duration} minutes...")
        
        metrics_result = collector.collect_metrics(
            duration_minutes=args.duration,
            step=args.step,
            namespaces=args.namespaces,
            cluster_issue_type=args.cluster_issue,
            categories=categories
        )
        
        print(f"Metrics collection complete!")
        print(f"Raw metrics saved to: {metrics_result['raw_file']}")
        print(f"Processed metrics saved to: {metrics_result['processed_file']}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 