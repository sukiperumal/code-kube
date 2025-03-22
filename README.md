# Kubernetes Resource Exhaustion Simulator

This project provides tools to create a Kubernetes cluster, simulate resource exhaustion scenarios, and collect metrics using Prometheus and Thanos.

## Prerequisites

- Docker Desktop (with Kubernetes enabled) or Minikube
- kubectl
- Helm
- Python 3.8+
- pip

## Setup Instructions

### 1. Install Python Dependencies

```bash
pip install kubernetes pyyaml
```

### 2. Create a Kubernetes Cluster

Using Minikube:

```bash
minikube start --nodes=3 --kubernetes-version=v1.26.3 --memory=2048 --addons=metrics-server
```

Or using kind:

```bash
kind create cluster --config kind-config.yaml --name metrics-demo
```

### 3. Deploy Monitoring Stack (Prometheus + Thanos)

```bash
# Create namespace
kubectl create namespace monitoring

# Apply Thanos object storage config
kubectl apply -f k8s/monitoring/thanos-objstore-secret.yaml

# Install Prometheus Operator with Thanos
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus-stack prometheus-community/kube-prometheus-stack -f k8s/monitoring/prometheus-values.yaml -n monitoring

# Apply service for stress pods
kubectl apply -f k8s/monitoring/stress-service.yaml
```

### 4. Access the Dashboards

Set up port forwarding for Grafana:

```bash
kubectl port-forward svc/prometheus-grafana 3000:80 -n monitoring
```

Then access Grafana at http://localhost:3000 with:
- Username: admin
- Password: prom-operator

## Running Resource Exhaustion Simulations

The simulation script supports different patterns of resource consumption:

1. **Random pattern**: Randomly allocates CPU and memory to each pod
2. **Gradual pattern**: Gradually increases resource usage
3. **Spike pattern**: Most pods use minimal resources, but a few use a lot

### Example Commands

```bash
# Run a random resource allocation pattern with 5 pods for 5 minutes
python src/simulation/resource_exhaustion.py --pattern random --pods 5 --duration 300

# Run a gradual load increase with 10 pods for 10 minutes
python src/simulation/resource_exhaustion.py --pattern gradual --pods 10 --duration 600

# Run a spike pattern with 8 pods for 5 minutes
python src/simulation/resource_exhaustion.py --pattern spike --pods 8 --duration 300
```

## Viewing Metrics

1. Open Grafana (http://localhost:3000)
2. Go to Explore
3. Select the Prometheus data source
4. Query for metrics with label matching: `{pod=~"stress-test.*"}`

## Thanos Configuration

This setup includes Thanos for long-term storage of metrics. The current configuration uses a local filesystem storage, but in a production environment, you would configure it to use object storage like S3, GCS, or Azure Blob Storage.

To view the Thanos UI:

```bash
kubectl port-forward svc/prometheus-stack-thanos-query 10902:9090 -n monitoring
```

Then access http://localhost:10902 in your browser.
