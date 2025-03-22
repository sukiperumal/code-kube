# Kubernetes Issue Predictor

An AI/ML system for predicting issues in Kubernetes clusters before they occur.

# Kubernetes Cluster Issue Data Collection

```bash
# Make the script executable
chmod +x collect_data.sh

# Run with default settings
./collect_data.sh

# Or with custom settings
./collect_data.sh --namespace my-namespace --iterations 5
```

### Testing Prometheus Connection

```bash
python3 collect_training_data.py --prometheus-url http://localhost:9090 --check-connection-only
```

## Generated Data

1. Raw metrics data in JSON format (in `data/raw/`)
2. Processed metrics data in CSV format (in `data/processed/`)
3. Combined training and testing datasets (in `data/datasets/`)

Each row in the CSV files includes various metrics collected from the cluster, along with a `cluster_issue_type` column that indicates the type of issue that was simulated:

- `resource`: Resource exhaustion (CPU, memory)
- `network`: Network issues
- `pod-failure`: Pod failures and crashes
- `none`: Normal operation (no issues)

## Customizing Data Collection

### Available Options

- `--namespace`: Kubernetes namespace to use for simulations (default: `ml-scenarios`)
- `--prometheus-url`: URL of the Prometheus server (default: `http://localhost:9090`)
- `--iterations`: Number of iterations per scenario type (default: 3)
- `--output-dir`: Directory to save the combined datasets (default: `data/datasets`)
- `--scenarios`: Scenario types to collect data for (Linux/shell script only)

### Advanced Configuration

For more advanced configuration, you can modify the `collect_training_data.py` script directly. 

- `duration_range`: Min/max duration of each simulation in seconds
- `pods_range`: Min/max number of pods to create for each simulation
- `patterns`: Patterns of issue simulation ("random", "gradual", "spike")
- `test_split`: Fraction of data to use for testing (default: 0.2 or 20%)

## Data Format

1. **Node-level metrics**:
   - CPU usage
   - Memory usage
   - Disk usage
   - Network traffic

2. **Pod-level metrics**:
   - Pod CPU usage
   - Pod memory usage
   - Pod network traffic
   - Pod restart counts

3. **Event data**:
   - Event counts by type (Normal, Warning, Error)
   - Event counts by reason (Created, Started, Failed, etc.)

4. **Issue type**:
   - `cluster_issue_type`: The type of issue that was simulated

## Example Usage

```bash
# Collect data with more iterations for better training
./collect_data.sh --iterations 10

# Focus on specific scenarios
./collect_data.sh --scenarios "resource network"

# Use a different namespace
./collect_data.sh --namespace testing-scenarios

# Connect to a different Prometheus server
./collect_data.sh --prometheus-url http://192.168.1.100:9090
```
