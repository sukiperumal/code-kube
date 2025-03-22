# Enhanced Kubernetes Metrics Collection

This package provides enhanced metrics collection capabilities for Kubernetes clusters. It collects a wide range of metrics and organizes them into meaningful categories that can be used for monitoring, alerting, and automated issue detection.

## Key Features

### Categorized Metrics Collection

The enhanced collector organizes metrics into the following well-defined categories:

- **container_runtime**: Metrics related to container performance and resource usage
- **service**: Service-level metrics including response times and availability
- **apiserver**: Kubernetes API server performance metrics
- **etcd**: Metrics for the etcd key-value store
- **loadbalancer**: Load balancer performance and throughput
- **ingress**: Ingress controller metrics
- **crd**: Custom Resource Definition metrics
- **scheduling**: Pod scheduling metrics
- **resource_quota**: Resource quota utilization
- **node**: Node-level resource utilization
- **pod**: Pod-level resource utilization

### Flexible Integration

The metrics collector can be used:

- As a standalone command-line utility
- Integrated into existing pipelines
- Used within a Python application
- During issue simulations to collect issue-specific metrics

### Continuous Collection Mode

The collector supports continuous mode, allowing you to collect metrics at specified intervals for long-running monitoring.

### Processed Output

Metrics are automatically processed into a tabular format (CSV), making them suitable for:

- ML model training
- Data analysis
- Anomaly detection
- Dashboard visualization

## Usage

### Basic Collection

To collect all metrics categories for the last 30 minutes:

```bash
python -m src.data_collection.collect_enhanced_metrics
```

### Specifying Categories

To collect only specific categories of metrics:

```bash
python -m src.data_collection.collect_enhanced_metrics --categories container_runtime apiserver etcd
```

### Continuous Collection

To collect metrics continuously at 5-minute intervals:

```bash
python -m src.data_collection.collect_enhanced_metrics --continuous --interval 300
```

### During Issue Simulations

To collect metrics during an issue simulation:

```bash
python -m src.data_collection.collect_enhanced_metrics --cluster-issue network-latency
```

## Visualization

You can easily generate Grafana dashboards for the collected metrics:

```bash
python -m src.data_collection.create_dashboards
```

This will create customized dashboards for each metric category, which can be:
- Saved as JSON files
- Uploaded directly to your Grafana instance

## Integration Examples

### Python Integration

```python
from src.data_collection.collector import KubernetesMetricsCollector

# Initialize the collector
collector = KubernetesMetricsCollector(prometheus_url="http://prometheus:9090")

# Collect specific metric categories
result = collector.collect_metrics(
    duration_minutes=15,
    step="15s",
    namespaces=["default", "kube-system"],
    categories=["container_runtime", "apiserver", "etcd"]
)

# Get the raw metrics and processed file path
raw_metrics = result["metrics"]
processed_file = result["processed_file"]
```

## Dependencies

- Prometheus deployment in your Kubernetes cluster
- Python 3.6+
- `prometheus-api-client`
- `kubernetes` Python client

## Troubleshooting

### Common Issues

1. **Prometheus connectivity**: Ensure your Prometheus instance is accessible from the environment running the collector

2. **No data for a category**: Verify that the relevant Prometheus exporters (e.g., node-exporter, kube-state-metrics) are deployed and working

3. **Missing a specific metric**: Some metrics may require specialized exporters or configuration changes. Check the Prometheus documentation for requirements. 