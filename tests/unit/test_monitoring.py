"""Unit tests for monitoring and observability components."""

import asyncio

import pytest

from src.monitoring.alerts import Alert, AlertManager, AlertSeverity, AlertStatus
from src.monitoring.health import HealthCheck, HealthChecker, HealthStatus


class TestMetricsCollector:
    """Test MetricsCollector class."""

    def test_counter_operations(self, metrics_collector):
        """Test counter metric operations."""
        collector = metrics_collector

        # Test increment
        collector.increment_counter("test_counter", 5)
        assert collector.get_counter_value("test_counter") == 5

        collector.increment_counter("test_counter", 3)
        assert collector.get_counter_value("test_counter") == 8

        # Test with labels
        collector.increment_counter("test_counter", 2, {"env": "test"})
        assert collector.get_counter_value("test_counter", {"env": "test"}) == 2

    def test_gauge_operations(self, metrics_collector):
        """Test gauge metric operations."""
        collector = metrics_collector

        # Test set gauge
        collector.set_gauge("test_gauge", 42.5)
        assert collector.get_gauge_value("test_gauge") == 42.5

        # Test update gauge
        collector.set_gauge("test_gauge", 100.0)
        assert collector.get_gauge_value("test_gauge") == 100.0

        # Test with labels
        collector.set_gauge("test_gauge", 75.0, {"service": "api"})
        assert collector.get_gauge_value("test_gauge", {"service": "api"}) == 75.0

    def test_histogram_operations(self, metrics_collector):
        """Test histogram metric operations."""
        collector = metrics_collector

        # Record some values
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for value in values:
            collector.record_histogram("test_histogram", value)

        # Get statistics
        stats = collector.get_histogram_stats("test_histogram")

        assert stats["count"] == 5
        assert stats["sum"] == 15.0
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["mean"] == 3.0

    def test_timer_context(self, metrics_collector):
        """Test timer context manager."""
        collector = metrics_collector

        with collector.time_operation("test_timer"):
            pass  # Simulate some work

        stats = collector.get_histogram_stats("test_timer")
        assert stats["count"] == 1
        assert stats["min"] >= 0
        assert stats["max"] >= 0

    def test_metrics_summary(self, metrics_collector):
        """Test metrics summary generation."""
        collector = metrics_collector

        # Add some metrics
        collector.increment_counter("requests", 10)
        collector.set_gauge("cpu_usage", 65.5)
        collector.record_histogram("latency", 0.5)

        summary = collector.get_metrics_summary()

        assert "timestamp" in summary
        assert "counters" in summary
        assert "gauges" in summary
        assert "histograms" in summary

        assert summary["counters"]["requests"] == 10
        assert summary["gauges"]["cpu_usage"] == 65.5

    def test_clear_metrics(self, metrics_collector):
        """Test metrics clearing."""
        collector = metrics_collector

        # Add some metrics
        collector.increment_counter("test_counter", 5)
        collector.set_gauge("test_gauge", 10.0)

        # Clear metrics
        collector.clear_metrics()

        # Verify cleared
        assert collector.get_counter_value("test_counter") == 0
        assert collector.get_gauge_value("test_gauge") == 0.0


class TestHealthChecker:
    """Test HealthChecker class."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test successful health check."""

        async def always_healthy():
            return True

        check = HealthCheck(
            name="test_check", check_function=always_healthy, timeout_seconds=1.0
        )

        result = await check.execute_check()
        assert result is True
        assert check.status == HealthStatus.HEALTHY
        assert check.consecutive_successes == 1
        assert check.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test failing health check."""

        async def always_failing():
            return False

        check = HealthCheck(
            name="test_check", check_function=always_failing, failure_threshold=2
        )

        # First failure should mark as degraded
        await check.execute_check()
        assert check.status == HealthStatus.DEGRADED

        # Second failure should mark as unhealthy
        await check.execute_check()
        assert check.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_health_check_timeout(self):
        """Test health check timeout."""

        async def slow_check():
            await asyncio.sleep(2.0)
            return True

        check = HealthCheck(
            name="test_check", check_function=slow_check, timeout_seconds=0.1
        )

        result = await check.execute_check()
        assert result is False
        assert "timed out" in check.last_error

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        """Test health check with exception."""

        async def failing_check():
            raise ValueError("Test error")

        check = HealthCheck(name="test_check", check_function=failing_check)

        result = await check.execute_check()
        assert result is False
        assert "Test error" in check.last_error

    @pytest.mark.asyncio
    async def test_health_checker_registration(self):
        """Test health check registration."""
        checker = HealthChecker()

        async def dummy_check():
            return True

        check = HealthCheck("test_check", dummy_check)
        checker.register_check(check)

        assert "test_check" in checker.health_checks

        # Test unregistration
        checker.unregister_check("test_check")
        assert "test_check" not in checker.health_checks

    @pytest.mark.asyncio
    async def test_check_all_healthy(self):
        """Test checking all health checks when healthy."""
        checker = HealthChecker()

        async def healthy_check():
            return True

        check1 = HealthCheck("check1", healthy_check)
        check2 = HealthCheck("check2", healthy_check)

        checker.register_check(check1)
        checker.register_check(check2)

        result = await checker.check_all()

        assert result["overall_status"] == HealthStatus.HEALTHY.value
        assert result["summary"]["healthy_checks"] == 2
        assert result["summary"]["unhealthy_checks"] == 0

    @pytest.mark.asyncio
    async def test_check_all_with_failures(self):
        """Test checking all when some checks fail."""
        checker = HealthChecker()

        async def healthy_check():
            return True

        async def unhealthy_check():
            return False

        check1 = HealthCheck("healthy", healthy_check)
        check2 = HealthCheck("unhealthy", unhealthy_check, failure_threshold=1)

        checker.register_check(check1)
        checker.register_check(check2)

        # Execute checks to set status
        await check1.execute_check()
        await check2.execute_check()

        result = await checker.check_all()

        assert result["overall_status"] == HealthStatus.UNHEALTHY.value

    def test_create_database_check(self):
        """Test database health check creation."""
        checker = HealthChecker()

        async def db_test():
            return True

        db_check = checker.create_database_check(db_test)

        assert db_check.name == "database"
        assert db_check.timeout_seconds == 5.0

    def test_create_memory_check(self):
        """Test memory health check creation."""
        checker = HealthChecker()

        memory_check = checker.create_memory_check(max_memory_mb=1000.0)

        assert memory_check.name == "memory"
        assert memory_check.timeout_seconds == 2.0


class TestAlertManager:
    """Test AlertManager class."""

    def test_alert_creation(self):
        """Test alert creation and basic properties."""

        def condition(context):
            return context.get("error_rate", 0) > 5.0

        alert = Alert(
            name="high_error_rate",
            description="Error rate is too high",
            severity=AlertSeverity.CRITICAL,
            condition_func=condition,
            cooldown_minutes=5,
        )

        assert alert.name == "high_error_rate"
        assert alert.severity == AlertSeverity.CRITICAL
        assert alert.status == AlertStatus.RESOLVED

    def test_alert_evaluation(self):
        """Test alert condition evaluation."""

        def condition(context):
            return context.get("error_rate", 0) > 5.0

        alert = Alert(
            name="test_alert",
            description="Test alert",
            severity=AlertSeverity.HIGH,
            condition_func=condition,
        )

        # Test condition not met
        context = {"error_rate": 3.0}
        result = alert.evaluate(context)
        assert result is False
        assert alert.status == AlertStatus.RESOLVED

        # Test condition met
        context = {"error_rate": 10.0}
        result = alert.evaluate(context)
        assert result is True
        assert alert.status == AlertStatus.ACTIVE

    def test_alert_cooldown(self):
        """Test alert cooldown functionality."""

        def condition(context):
            return True

        alert = Alert(
            name="test_alert",
            description="Test alert",
            severity=AlertSeverity.MEDIUM,
            condition_func=condition,
            cooldown_minutes=10,
        )

        # First evaluation should allow notification
        alert.evaluate({})
        assert alert.should_notify() is True

        # Mark as notified
        alert.mark_notified()

        # Second evaluation should not allow notification (cooldown)
        alert.evaluate({})
        assert alert.should_notify() is False

    def test_alert_auto_resolve(self):
        """Test alert auto-resolution."""

        def condition(context):
            return context.get("trigger", False)

        alert = Alert(
            name="test_alert",
            description="Test alert",
            severity=AlertSeverity.LOW,
            condition_func=condition,
            auto_resolve=True,
        )

        # Trigger alert
        alert.evaluate({"trigger": True})
        assert alert.status == AlertStatus.ACTIVE

        # Condition no longer met - should auto-resolve
        alert.evaluate({"trigger": False})
        assert alert.status == AlertStatus.RESOLVED

    def test_alert_suppression(self):
        """Test alert suppression."""

        def condition(context):
            return True

        alert = Alert(
            name="test_alert",
            description="Test alert",
            severity=AlertSeverity.HIGH,
            condition_func=condition,
        )

        # Suppress alert
        alert.suppress()
        assert alert.status == AlertStatus.SUPPRESSED

        # Unsuppress alert
        alert.unsuppress()
        assert alert.status == AlertStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_alert_manager_registration(self):
        """Test alert registration in alert manager."""
        manager = AlertManager()

        def condition(context):
            return False

        alert = Alert("test", "Test alert", AlertSeverity.LOW, condition)
        manager.register_alert(alert)

        assert "test" in manager.alerts

        # Test unregistration
        manager.unregister_alert("test")
        assert "test" not in manager.alerts

    @pytest.mark.asyncio
    async def test_alert_manager_evaluation(self):
        """Test alert evaluation by manager."""
        manager = AlertManager()

        def condition(context):
            return context.get("trigger", False)

        alert = Alert("test", "Test alert", AlertSeverity.MEDIUM, condition)
        manager.register_alert(alert)

        # Test with condition not met
        triggered = await manager.evaluate_alerts({"trigger": False})
        assert len(triggered) == 0

        # Test with condition met
        triggered = await manager.evaluate_alerts({"trigger": True})
        assert len(triggered) == 1
        assert triggered[0].name == "test"

    @pytest.mark.asyncio
    async def test_alert_suppression_by_manager(self):
        """Test alert suppression through manager."""
        manager = AlertManager()

        def condition(context):
            return True

        alert = Alert("test", "Test alert", AlertSeverity.HIGH, condition)
        manager.register_alert(alert)

        # Suppress alert
        result = manager.suppress_alert("test")
        assert result is True
        assert "test" in manager.suppressed_alerts

        # Evaluate - should not trigger suppressed alert
        triggered = await manager.evaluate_alerts({})
        assert len(triggered) == 0

        # Unsuppress
        result = manager.unsuppress_alert("test")
        assert result is True
        assert "test" not in manager.suppressed_alerts

    def test_alert_status_reporting(self):
        """Test alert status reporting."""
        manager = AlertManager()

        def condition(context):
            return False

        alert = Alert("test", "Test alert", AlertSeverity.LOW, condition)
        manager.register_alert(alert)

        status = manager.get_alert_status()

        assert "timestamp" in status
        assert "total_alerts" in status
        assert "alerts" in status
        assert status["total_alerts"] == 1
        assert "test" in status["alerts"]

    def test_predefined_alerts(self):
        """Test predefined alert creation methods."""
        manager = AlertManager()

        # Test prediction latency alert
        latency_alert = manager.create_prediction_latency_alert(1.0)
        assert latency_alert.name == "high_prediction_latency"
        assert latency_alert.severity == AlertSeverity.HIGH

        # Test error rate alert
        error_alert = manager.create_error_rate_alert(5.0)
        assert error_alert.name == "high_error_rate"
        assert error_alert.severity == AlertSeverity.CRITICAL

    def test_alert_info_collection(self):
        """Test alert information collection."""

        def condition(context):
            return context.get("value", 0) > 10

        alert = Alert(
            name="test_alert",
            description="Test alert",
            severity=AlertSeverity.HIGH,
            condition_func=condition,
            tags={"component": "test"},
        )

        # Trigger alert
        alert.evaluate({"value": 15})

        info = alert.get_info()

        assert info["name"] == "test_alert"
        assert info["description"] == "Test alert"
        assert info["severity"] == "high"
        assert info["status"] == "active"
        assert info["trigger_count"] == 1
        assert info["tags"]["component"] == "test"
        assert info["current_context"]["value"] == 15
