import numpy as np
from prometheus_api_client import PrometheusConnect
from datetime import datetime, timedelta
import os
import json

class EnhancedMetricsCollector:
    """
    A class to collect enhanced metrics from Kubernetes clusters
    that extends the basic metrics collection capabilities.
    """
    
    def __init__(self, prometheus_connector=None, prometheus_url=None):
        """Initialize with either an existing PrometheusConnect instance or a URL."""
        self.prometheus_connector = prometheus_connector
        
        if self.prometheus_connector is None and prometheus_url is not None:
            self.prometheus_connector = PrometheusConnect(url=prometheus_url, disable_ssl=True)
        
        if self.prometheus_connector is None:
            raise ValueError("Either prometheus_connector or prometheus_url must be provided")
    
    def query_prometheus(self, query, start_time=None, end_time=None, step="15s"):
        """Query Prometheus for the given PromQL query over the specified time range."""
        if start_time is None:
            start_time = datetime.now() - timedelta(minutes=30)
        if end_time is None:
            end_time = datetime.now()
            
        result = self.prometheus_connector.custom_query_range(
            query=query,
            start_time=start_time,
            end_time=end_time,
            step=step
        )
        return result
    
    def collect_container_runtime_metrics(self, start_time=None, end_time=None, step="15s", namespaces=None):
        """
        Collect container runtime metrics (Docker/containerd).
        """
        if namespaces:
            namespace_selector = '|'.join(namespaces)
            namespace_filter = f'namespace=~"{namespace_selector}"'
        else:
            namespace_filter = ""
        
        metrics = {
            "container_runtime_cpu_usage": f'sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{{{namespace_filter}}}[5m]))',
            "container_runtime_memory_usage": f'sum by (namespace, pod, container) (container_memory_working_set_bytes{{{namespace_filter}}})',
            "container_runtime_memory_failures": f'sum by (namespace, pod, container, scope, type) (rate(container_memory_failures_total{{{namespace_filter}}}[5m]))',
            "container_runtime_processes": f'sum by (namespace, pod, container) (container_processes{{{namespace_filter}}})',
            "container_runtime_threads": f'sum by (namespace, pod, container) (container_threads{{{namespace_filter}}})',
            "container_runtime_io_reads": f'sum by (namespace, pod, container) (rate(container_fs_reads_bytes_total{{{namespace_filter}}}[5m]))',
            "container_runtime_io_writes": f'sum by (namespace, pod, container) (rate(container_fs_writes_bytes_total{{{namespace_filter}}}[5m]))',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_service_metrics(self, start_time=None, end_time=None, step="15s", namespaces=None):
        """
        Collect service response times and availability metrics.
        """
        if namespaces:
            namespace_selector = '|'.join(namespaces)
            namespace_filter = f'namespace=~"{namespace_selector}"'
        else:
            namespace_filter = ""
        
        metrics = {
            # Service latencies (if using Istio)
            "service_request_duration": f'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket{{{namespace_filter}}}[5m])) by (destination_service, le))',
            
            # Service availability (success rate)
            "service_success_rate": f'sum(rate(istio_requests_total{{{namespace_filter}, response_code=~"2.."}}[5m])) by (destination_service) / sum(rate(istio_requests_total{{{namespace_filter}}}[5m])) by (destination_service)',
            
            # For non-Istio clusters, use endpoint metrics if available
            "endpoint_response_time": f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{{namespace_filter}}}[5m])) by (service, le))',
            
            # Service endpoint availability
            "endpoint_availability": f'sum by (namespace, service, endpoint) (up{{{namespace_filter}}})',
            
            # Error rate by service
            "service_error_rate": f'sum(rate(http_requests_total{{{namespace_filter}, code=~"5.."}}[5m])) by (service) / sum(rate(http_requests_total{{{namespace_filter}}}[5m])) by (service)',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_apiserver_metrics(self, start_time=None, end_time=None, step="15s"):
        """
        Collect API server latency and related metrics.
        """
        metrics = {
            # API server request latency
            "apiserver_request_latency": 'histogram_quantile(0.95, sum(rate(apiserver_request_duration_seconds_bucket[5m])) by (verb, resource, le))',
            
            # API server request rate
            "apiserver_request_rate": 'sum(rate(apiserver_request_total[5m])) by (verb, resource, code)',
            
            # API server error rate
            "apiserver_error_rate": 'sum(rate(apiserver_request_total{code=~"5.."}[5m])) / sum(rate(apiserver_request_total[5m]))',
            
            # API server request terminations
            "apiserver_request_terminations": 'sum(rate(apiserver_request_terminations_total[5m])) by (component, verb)',
            
            # API server client certificate expirations
            "apiserver_client_cert_expiry": 'apiserver_client_certificate_expiration_seconds_count',
            
            # Webhook latency if using admission webhooks
            "webhook_latency": 'histogram_quantile(0.95, sum(rate(apiserver_admission_webhook_admission_duration_seconds_bucket[5m])) by (name, le))',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_etcd_metrics(self, start_time=None, end_time=None, step="15s"):
        """
        Collect etcd metrics including leader election and request latency.
        """
        metrics = {
            # etcd has a leader (should be 1)
            "etcd_has_leader": 'etcd_server_has_leader',
            
            # etcd leader changes
            "etcd_leader_changes": 'sum(rate(etcd_server_leader_changes_seen_total[5m]))',
            
            # etcd proposal failures
            "etcd_proposal_failures": 'sum(rate(etcd_server_proposals_failed_total[5m]))',
            
            # etcd request latency
            "etcd_request_latency": 'histogram_quantile(0.95, sum(rate(etcd_request_duration_seconds_bucket[5m])) by (operation, le))',
            
            # etcd disk operations latency
            "etcd_disk_latency": 'histogram_quantile(0.95, sum(rate(etcd_disk_backend_commit_duration_seconds_bucket[5m])) by (le))',
            
            # etcd compaction duration
            "etcd_compaction_duration": 'histogram_quantile(0.95, sum(rate(etcd_debugging_mvcc_db_compaction_duration_seconds_bucket[5m])) by (le))',
            
            # etcd network latency
            "etcd_network_latency": 'histogram_quantile(0.95, sum(rate(etcd_network_peer_round_trip_time_seconds_bucket[5m])) by (To, le))',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_loadbalancer_metrics(self, start_time=None, end_time=None, step="15s"):
        """
        Collect load balancer metrics.
        """
        metrics = {
            # Load balancer request rate (if using ingress-nginx)
            "lb_request_rate": 'sum(rate(nginx_ingress_controller_requests[5m])) by (ingress, service)',
            
            # Load balancer response time
            "lb_response_time": 'histogram_quantile(0.95, sum(rate(nginx_ingress_controller_request_duration_seconds_bucket[5m])) by (ingress, service, le))',
            
            # Load balancer error rate
            "lb_error_rate": 'sum(rate(nginx_ingress_controller_requests{status=~"5.."}[5m])) by (ingress, service) / sum(rate(nginx_ingress_controller_requests[5m])) by (ingress, service)',
            
            # Connection statistics
            "lb_connections": 'sum(nginx_ingress_controller_nginx_process_connections) by (state)',
            
            # SSL handshake failures
            "lb_ssl_handshake_failures": 'sum(rate(nginx_ingress_controller_ssl_expire_time_seconds[5m]))',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_ingress_metrics(self, start_time=None, end_time=None, step="15s"):
        """
        Collect ingress controller metrics.
        """
        metrics = {
            # Ingress controller success rate
            "ingress_success_rate": 'sum(rate(nginx_ingress_controller_requests{status=~"2.."}[5m])) / sum(rate(nginx_ingress_controller_requests[5m]))',
            
            # Ingress controller latency
            "ingress_latency": 'histogram_quantile(0.95, sum(rate(nginx_ingress_controller_request_duration_seconds_bucket[5m])) by (ingress, le))',
            
            # Ingress controller request rate
            "ingress_request_rate": 'sum(rate(nginx_ingress_controller_requests[5m])) by (ingress, path)',
            
            # Ingress controller upstream latency (backend service response time)
            "ingress_upstream_latency": 'histogram_quantile(0.95, sum(rate(nginx_ingress_controller_response_duration_seconds_bucket[5m])) by (ingress, le))',
            
            # Socket errors
            "ingress_socket_errors": 'sum(rate(nginx_ingress_controller_request_size_bucket[5m])) by (ingress)',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_crd_metrics(self, start_time=None, end_time=None, step="15s"):
        """
        Collect metrics related to Custom Resource Definitions (CRDs).
        """
        metrics = {
            # Count of custom resources by type
            "crd_instance_count": 'sum(kube_customresource_total) by (namespace, group, version, resource)',
            
            # Custom controller processing metrics (if they expose Prometheus metrics)
            "crd_controller_reconcile_time": 'histogram_quantile(0.95, sum(rate(controller_runtime_reconcile_time_seconds_bucket[5m])) by (controller, le))',
            
            # Custom controller queue depth
            "crd_controller_queue_depth": 'sum(workqueue_depth) by (name)',
            
            # Custom controller work duration
            "crd_controller_work_duration": 'histogram_quantile(0.95, sum(rate(workqueue_work_duration_seconds_bucket[5m])) by (name, le))',
            
            # Custom controller retries
            "crd_controller_retries": 'sum(rate(workqueue_retries_total[5m])) by (name)',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_scheduling_metrics(self, start_time=None, end_time=None, step="15s"):
        """
        Collect pod scheduling latency metrics.
        """
        metrics = {
            # Pod scheduling attempts
            "scheduling_attempts": 'sum(rate(scheduler_schedule_attempts_total[5m])) by (result)',
            
            # Pod scheduling latency
            "scheduling_latency": 'histogram_quantile(0.95, sum(rate(scheduler_scheduling_algorithm_duration_seconds_bucket[5m])) by (le))',
            
            # Pod scheduling e2e latency
            "scheduling_e2e_latency": 'histogram_quantile(0.95, sum(rate(scheduler_e2e_scheduling_duration_seconds_bucket[5m])) by (le))',
            
            # Pending pods
            "pending_pods": 'sum(kube_pod_status_phase{phase="Pending"}) by (namespace)',
            
            # Preemption attempts
            "pod_preemptions": 'rate(scheduler_pod_preemption_victims[5m])',
            
            # Scheduling errors
            "scheduling_errors": 'sum(rate(scheduler_schedule_attempts_total{result="error"}[5m]))',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_resource_quota_metrics(self, start_time=None, end_time=None, step="15s", namespaces=None):
        """
        Collect resource quota utilization metrics.
        """
        if namespaces:
            namespace_selector = '|'.join(namespaces)
            namespace_filter = f'namespace=~"{namespace_selector}"'
        else:
            namespace_filter = ""
        
        metrics = {
            # Resource quota utilization
            "quota_cpu_usage": f'sum(kube_resourcequota{{{namespace_filter}, resource="requests.cpu", type="used"}}) by (namespace, resource, quota_name) / sum(kube_resourcequota{{{namespace_filter}, resource="requests.cpu", type="hard"}}) by (namespace, resource, quota_name)',
            "quota_memory_usage": f'sum(kube_resourcequota{{{namespace_filter}, resource="requests.memory", type="used"}}) by (namespace, resource, quota_name) / sum(kube_resourcequota{{{namespace_filter}, resource="requests.memory", type="hard"}}) by (namespace, resource, quota_name)',
            "quota_pods_usage": f'sum(kube_resourcequota{{{namespace_filter}, resource="pods", type="used"}}) by (namespace, resource, quota_name) / sum(kube_resourcequota{{{namespace_filter}, resource="pods", type="hard"}}) by (namespace, resource, quota_name)',
            
            # Absolute resource quota values
            "quota_cpu_hard": f'sum(kube_resourcequota{{{namespace_filter}, resource="requests.cpu", type="hard"}}) by (namespace, quota_name)',
            "quota_memory_hard": f'sum(kube_resourcequota{{{namespace_filter}, resource="requests.memory", type="hard"}}) by (namespace, quota_name)',
            "quota_cpu_used": f'sum(kube_resourcequota{{{namespace_filter}, resource="requests.cpu", type="used"}}) by (namespace, quota_name)',
            "quota_memory_used": f'sum(kube_resourcequota{{{namespace_filter}, resource="requests.memory", type="used"}}) by (namespace, quota_name)',
            
            # LimitRange metrics
            "limit_range_defaults": f'kube_limitrange{{{namespace_filter}}} by (namespace, resource, type, constraint)',
        }
        
        result = {}
        for metric_name, query in metrics.items():
            print(f"Collecting {metric_name}...")
            result[metric_name] = self.query_prometheus(query, start_time, end_time, step)
        
        return result
    
    def collect_all_enhanced_metrics(self, start_time=None, end_time=None, step="15s", namespaces=None):
        """
        Collect all enhanced metrics.
        
        Args:
            start_time: Start time for queries
            end_time: End time for queries
            step: Step interval for queries
            namespaces: List of namespaces to collect metrics for
            
        Returns:
            dict: Dictionary with all enhanced metrics
        """
        if namespaces is None:
            namespaces = ["default", "kube-system"]
            
        result = {
            "container_runtime": self.collect_container_runtime_metrics(start_time, end_time, step, namespaces),
            "service": self.collect_service_metrics(start_time, end_time, step, namespaces),
            "apiserver": self.collect_apiserver_metrics(start_time, end_time, step),
            "etcd": self.collect_etcd_metrics(start_time, end_time, step),
            "loadbalancer": self.collect_loadbalancer_metrics(start_time, end_time, step),
            "ingress": self.collect_ingress_metrics(start_time, end_time, step),
            "crd": self.collect_crd_metrics(start_time, end_time, step),
            "scheduling": self.collect_scheduling_metrics(start_time, end_time, step),
            "resource_quota": self.collect_resource_quota_metrics(start_time, end_time, step, namespaces)
        }
        
        return result 