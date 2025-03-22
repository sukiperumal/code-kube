#!/bin/bash
# Kubernetes Cluster Issue Data Collection Script 
# This script collects metrics from simulated cluster issues

echo "Kubernetes Cluster Issue Data Collection"
echo "----------------------------------------"

# Set default values
NAMESPACE="ml-scenarios"
PROMETHEUS_URL="http://localhost:9090"
ITERATIONS=3
OUTPUT_DIR="data/datasets"
SCENARIOS="resource network pod-failure none"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --prometheus-url)
      PROMETHEUS_URL="$2"
      shift 2
      ;;
    --iterations)
      ITERATIONS="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --scenarios)
      SCENARIOS="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      shift
      ;;
  esac
done

echo "Starting data collection with the following parameters:"
echo "Namespace: $NAMESPACE"
echo "Prometheus URL: $PROMETHEUS_URL"
echo "Iterations per scenario: $ITERATIONS"
echo "Output directory: $OUTPUT_DIR"
echo "Scenarios: $SCENARIOS"
echo

# Create directories
mkdir -p data/raw data/processed "$OUTPUT_DIR"

# First check if Prometheus is accessible
echo "Checking connection to Prometheus..."
python3 collect_training_data.py --prometheus-url "$PROMETHEUS_URL" --check-connection-only
if [ $? -ne 0 ]; then
  echo
  echo "Failed to connect to Prometheus. Please check the URL and try again."
  echo "If you're using a local Prometheus instance, try:"
  echo "./collect_data.sh --prometheus-url http://localhost:9090"
  echo
  exit 1
fi

# Run the data collection script
python3 collect_training_data.py \
  --namespace "$NAMESPACE" \
  --prometheus-url "$PROMETHEUS_URL" \
  --iterations "$ITERATIONS" \
  --output-dir "$OUTPUT_DIR" \
  --scenarios $SCENARIOS

echo
echo "Data collection complete. Check $OUTPUT_DIR for the resulting datasets." 