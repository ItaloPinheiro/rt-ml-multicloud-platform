"""Metrics collection and monitoring for ML pipeline components."""

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        start_http_server,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

logger = structlog.get_logger()


class MetricsCollector:
    """Base metrics collector for tracking application metrics."""

    def __init__(self, max_history: int = 1000):
        """Initialize metrics collector.

        Args:
            max_history: Maximum number of historical data points to keep
        """
        self.max_history = max_history
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = defaultdict(float)
        self.histograms: Dict[str, List[float]] = defaultdict(list)
        self.lock = threading.Lock()
        self.logger = logger.bind(component="MetricsCollector")

    def increment_counter(
        self, name: str, value: int = 1, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Increment a counter metric.

        Args:
            name: Counter name
            value: Value to add
            labels: Optional labels for the metric
        """
        with self.lock:
            metric_key = self._build_metric_key(name, labels)
            self.counters[metric_key] += value

            # Store historical data
            self.metrics[metric_key].append(
                {
                    "timestamp": datetime.now(timezone.utc),
                    "value": self.counters[metric_key],
                    "delta": value,
                    "type": "counter",
                    "labels": labels or {},
                }
            )

    def set_gauge(
        self, name: str, value: float, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Set a gauge metric value.

        Args:
            name: Gauge name
            value: Value to set
            labels: Optional labels for the metric
        """
        with self.lock:
            metric_key = self._build_metric_key(name, labels)
            self.gauges[metric_key] = value

            # Store historical data
            self.metrics[metric_key].append(
                {
                    "timestamp": datetime.now(timezone.utc),
                    "value": value,
                    "type": "gauge",
                    "labels": labels or {},
                }
            )

    def record_histogram(
        self, name: str, value: float, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a value in a histogram metric.

        Args:
            name: Histogram name
            value: Value to record
            labels: Optional labels for the metric
        """
        with self.lock:
            metric_key = self._build_metric_key(name, labels)
            self.histograms[metric_key].append(value)

            # Store historical data
            self.metrics[metric_key].append(
                {
                    "timestamp": datetime.now(timezone.utc),
                    "value": value,
                    "type": "histogram",
                    "labels": labels or {},
                }
            )

    def time_operation(self, name: str, labels: Optional[Dict[str, str]] = None):
        """Context manager for timing operations.

        Args:
            name: Timer name
            labels: Optional labels for the metric

        Returns:
            Context manager that records operation duration
        """
        return TimerContext(self, name, labels)

    def get_counter_value(
        self, name: str, labels: Optional[Dict[str, str]] = None
    ) -> int:
        """Get current counter value.

        Args:
            name: Counter name
            labels: Optional labels

        Returns:
            Current counter value
        """
        metric_key = self._build_metric_key(name, labels)
        return self.counters.get(metric_key, 0)

    def get_gauge_value(
        self, name: str, labels: Optional[Dict[str, str]] = None
    ) -> float:
        """Get current gauge value.

        Args:
            name: Gauge name
            labels: Optional labels

        Returns:
            Current gauge value
        """
        metric_key = self._build_metric_key(name, labels)
        return self.gauges.get(metric_key, 0.0)

    def get_histogram_stats(
        self, name: str, labels: Optional[Dict[str, str]] = None
    ) -> Dict[str, float]:
        """Get histogram statistics.

        Args:
            name: Histogram name
            labels: Optional labels

        Returns:
            Dictionary with histogram statistics
        """
        metric_key = self._build_metric_key(name, labels)
        values = self.histograms.get(metric_key, [])

        if not values:
            return {}

        sorted_values = sorted(values)
        count = len(values)

        return {
            "count": count,
            "sum": sum(values),
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "mean": sum(values) / count,
            "p50": sorted_values[int(count * 0.5)],
            "p90": sorted_values[int(count * 0.9)],
            "p95": sorted_values[int(count * 0.95)],
            "p99": sorted_values[int(count * 0.99)],
        }

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all metrics.

        Returns:
            Dictionary with metrics summary
        """
        with self.lock:
            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "histograms": {
                    name: self.get_histogram_stats(
                        name.split("|")[0], self._parse_labels_from_key(name)
                    )
                    for name in self.histograms.keys()
                },
            }

        return summary

    def clear_metrics(self) -> None:
        """Clear all metrics data."""
        with self.lock:
            self.metrics.clear()
            self.counters.clear()
            self.gauges.clear()
            self.histograms.clear()

        self.logger.info("All metrics cleared")

    def _build_metric_key(
        self, name: str, labels: Optional[Dict[str, str]] = None
    ) -> str:
        """Build metric key with labels.

        Args:
            name: Metric name
            labels: Optional labels

        Returns:
            Metric key string
        """
        if not labels:
            return name

        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}|{label_str}"

    def _parse_labels_from_key(self, key: str) -> Optional[Dict[str, str]]:
        """Parse labels from metric key.

        Args:
            key: Metric key

        Returns:
            Labels dictionary or None
        """
        if "|" not in key:
            return None

        _, label_str = key.split("|", 1)
        labels = {}

        for pair in label_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                labels[k] = v

        return labels


class TimerContext:
    """Context manager for timing operations."""

    def __init__(
        self,
        collector: MetricsCollector,
        name: str,
        labels: Optional[Dict[str, str]] = None,
    ):
        """Initialize timer context.

        Args:
            collector: Metrics collector instance
            name: Timer name
            labels: Optional labels
        """
        self.collector = collector
        self.name = name
        self.labels = labels
        self.start_time = None

    def __enter__(self):
        """Start timing."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timing and record duration."""
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.collector.record_histogram(self.name, duration, self.labels)


class PrometheusMetrics:
    """Prometheus metrics collector and exporter."""

    def __init__(self, port: int = 8000, prefix: str = "ml_pipeline"):
        """Initialize Prometheus metrics.

        Args:
            port: Port for metrics HTTP server
            prefix: Metric name prefix
        """
        if not PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus_client is not available. Install with: pip install prometheus-client"
            )

        self.port = port
        self.prefix = prefix
        self.metrics_server_started = False
        self.logger = logger.bind(component="PrometheusMetrics")

        # Initialize common metrics
        self._init_metrics()

    def _init_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        # Prediction metrics
        self.prediction_requests_total = Counter(
            f"{self.prefix}_prediction_requests_total",
            "Total number of prediction requests",
            ["model_name", "model_version", "status"],
        )

        self.prediction_duration_seconds = Histogram(
            f"{self.prefix}_prediction_duration_seconds",
            "Prediction request duration in seconds",
            ["model_name", "model_version"],
            buckets=[
                0.001,
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1.0,
                2.5,
                5.0,
                10.0,
            ],
        )

        # Model metrics
        self.models_loaded_total = Gauge(
            f"{self.prefix}_models_loaded_total", "Number of models currently loaded"
        )

        self.model_load_duration_seconds = Histogram(
            f"{self.prefix}_model_load_duration_seconds",
            "Model loading duration in seconds",
            ["model_name", "model_version"],
        )

        # Feature store metrics
        self.feature_requests_total = Counter(
            f"{self.prefix}_feature_requests_total",
            "Total number of feature requests",
            ["feature_group", "operation", "status"],
        )

        self.feature_cache_hits_total = Counter(
            f"{self.prefix}_feature_cache_hits_total",
            "Total number of feature cache hits",
            ["feature_group"],
        )

        self.feature_cache_misses_total = Counter(
            f"{self.prefix}_feature_cache_misses_total",
            "Total number of feature cache misses",
            ["feature_group"],
        )

        # Data ingestion metrics
        self.ingestion_messages_total = Counter(
            f"{self.prefix}_ingestion_messages_total",
            "Total number of ingested messages",
            ["source", "status"],
        )

        self.ingestion_lag_seconds = Gauge(
            f"{self.prefix}_ingestion_lag_seconds",
            "Current ingestion lag in seconds",
            ["source"],
        )

        # System metrics
        self.memory_usage_bytes = Gauge(
            f"{self.prefix}_memory_usage_bytes", "Memory usage in bytes"
        )

        self.cpu_usage_percent = Gauge(
            f"{self.prefix}_cpu_usage_percent", "CPU usage percentage"
        )

        # Error metrics
        self.errors_total = Counter(
            f"{self.prefix}_errors_total",
            "Total number of errors",
            ["component", "error_type"],
        )

    def start_metrics_server(self) -> None:
        """Start Prometheus metrics HTTP server."""
        if self.metrics_server_started:
            self.logger.warning("Metrics server already started")
            return

        try:
            start_http_server(self.port)
            self.metrics_server_started = True
            self.logger.info(f"Prometheus metrics server started on port {self.port}")
        except Exception as e:
            self.logger.error(f"Failed to start metrics server: {str(e)}")
            raise

    def record_prediction(
        self,
        model_name: str,
        model_version: str,
        duration: float,
        status: str = "success",
    ) -> None:
        """Record a prediction request.

        Args:
            model_name: Name of the model
            model_version: Version of the model
            duration: Request duration in seconds
            status: Request status (success/error)
        """
        self.prediction_requests_total.labels(
            model_name=model_name, model_version=model_version, status=status
        ).inc()

        self.prediction_duration_seconds.labels(
            model_name=model_name, model_version=model_version
        ).observe(duration)

    def record_model_load(
        self, model_name: str, model_version: str, duration: float
    ) -> None:
        """Record a model loading operation.

        Args:
            model_name: Name of the model
            model_version: Version of the model
            duration: Load duration in seconds
        """
        self.model_load_duration_seconds.labels(
            model_name=model_name, model_version=model_version
        ).observe(duration)

    def set_models_loaded(self, count: int) -> None:
        """Set the number of currently loaded models.

        Args:
            count: Number of loaded models
        """
        self.models_loaded_total.set(count)

    def record_feature_request(
        self, feature_group: str, operation: str, status: str = "success"
    ) -> None:
        """Record a feature store request.

        Args:
            feature_group: Feature group name
            operation: Operation type (get/put/delete)
            status: Request status
        """
        self.feature_requests_total.labels(
            feature_group=feature_group, operation=operation, status=status
        ).inc()

    def record_feature_cache_hit(self, feature_group: str) -> None:
        """Record a feature cache hit.

        Args:
            feature_group: Feature group name
        """
        self.feature_cache_hits_total.labels(feature_group=feature_group).inc()

    def record_feature_cache_miss(self, feature_group: str) -> None:
        """Record a feature cache miss.

        Args:
            feature_group: Feature group name
        """
        self.feature_cache_misses_total.labels(feature_group=feature_group).inc()

    def record_ingestion_message(self, source: str, status: str = "success") -> None:
        """Record an ingested message.

        Args:
            source: Ingestion source (kafka/pubsub/kinesis)
            status: Ingestion status
        """
        self.ingestion_messages_total.labels(source=source, status=status).inc()

    def set_ingestion_lag(self, source: str, lag_seconds: float) -> None:
        """Set ingestion lag for a source.

        Args:
            source: Ingestion source
            lag_seconds: Lag in seconds
        """
        self.ingestion_lag_seconds.labels(source=source).set(lag_seconds)

    def set_memory_usage(self, bytes_used: int) -> None:
        """Set memory usage.

        Args:
            bytes_used: Memory usage in bytes
        """
        self.memory_usage_bytes.set(bytes_used)

    def set_cpu_usage(self, percent: float) -> None:
        """Set CPU usage percentage.

        Args:
            percent: CPU usage percentage
        """
        self.cpu_usage_percent.set(percent)

    def record_error(self, component: str, error_type: str) -> None:
        """Record an error.

        Args:
            component: Component where error occurred
            error_type: Type of error
        """
        self.errors_total.labels(component=component, error_type=error_type).inc()

    def get_metrics(self) -> str:
        """Get current metrics in Prometheus format.

        Returns:
            Metrics in Prometheus exposition format
        """
        return generate_latest().decode("utf-8")
