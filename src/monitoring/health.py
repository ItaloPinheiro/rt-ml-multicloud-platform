"""Health checking and service monitoring for ML pipeline components."""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

logger = structlog.get_logger()


class HealthStatus(Enum):
    """Health status enumeration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheck:
    """Individual health check definition."""

    def __init__(
        self,
        name: str,
        check_function: Callable[[], Awaitable[bool]],
        timeout_seconds: float = 5.0,
        interval_seconds: float = 30.0,
        failure_threshold: int = 3,
        success_threshold: int = 1,
    ):
        """Initialize health check.

        Args:
            name: Name of the health check
            check_function: Async function that returns True if healthy
            timeout_seconds: Timeout for the check
            interval_seconds: Interval between checks
            failure_threshold: Number of failures before marking unhealthy
            success_threshold: Number of successes before marking healthy
        """
        self.name = name
        self.check_function = check_function
        self.timeout_seconds = timeout_seconds
        self.interval_seconds = interval_seconds
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold

        # State tracking
        self.status = HealthStatus.UNKNOWN
        self.last_check_time: Optional[datetime] = None
        self.last_success_time: Optional[datetime] = None
        self.last_failure_time: Optional[datetime] = None
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.total_checks = 0
        self.total_failures = 0
        self.last_error: Optional[str] = None

    async def execute_check(self) -> bool:
        """Execute the health check.

        Returns:
            True if healthy, False otherwise
        """
        self.last_check_time = datetime.now(timezone.utc)
        self.total_checks += 1

        try:
            # Execute check with timeout
            result = await asyncio.wait_for(
                self.check_function(), timeout=self.timeout_seconds
            )

            if result:
                self._record_success()
            else:
                self._record_failure("Check returned False")

            return result

        except asyncio.TimeoutError:
            self._record_failure(f"Check timed out after {self.timeout_seconds}s")
            return False
        except Exception as e:
            self._record_failure(f"Check failed with exception: {str(e)}")
            return False

    def _record_success(self) -> None:
        """Record a successful check."""
        self.last_success_time = datetime.now(timezone.utc)
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_error = None

        # Update status based on success threshold
        if self.consecutive_successes >= self.success_threshold:
            self.status = HealthStatus.HEALTHY

    def _record_failure(self, error_message: str) -> None:
        """Record a failed check.

        Args:
            error_message: Error message from the failure
        """
        self.last_failure_time = datetime.now(timezone.utc)
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.total_failures += 1
        self.last_error = error_message

        # Update status based on failure threshold
        if self.consecutive_failures >= self.failure_threshold:
            self.status = HealthStatus.UNHEALTHY
        elif self.consecutive_failures > 0:
            self.status = HealthStatus.DEGRADED

    def get_status_info(self) -> Dict[str, Any]:
        """Get detailed status information.

        Returns:
            Dictionary with health check status details
        """
        return {
            "name": self.name,
            "status": self.status.value,
            "last_check_time": (
                self.last_check_time.isoformat() if self.last_check_time else None
            ),
            "last_success_time": (
                self.last_success_time.isoformat() if self.last_success_time else None
            ),
            "last_failure_time": (
                self.last_failure_time.isoformat() if self.last_failure_time else None
            ),
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "success_rate": (
                (self.total_checks - self.total_failures) / self.total_checks
                if self.total_checks > 0
                else 0
            ),
            "last_error": self.last_error,
            "configuration": {
                "timeout_seconds": self.timeout_seconds,
                "interval_seconds": self.interval_seconds,
                "failure_threshold": self.failure_threshold,
                "success_threshold": self.success_threshold,
            },
        }


class HealthChecker:
    """Centralized health checking system for ML pipeline components."""

    def __init__(self):
        """Initialize health checker."""
        self.health_checks: Dict[str, HealthCheck] = {}
        self.running = False
        self.check_task: Optional[asyncio.Task] = None
        self.start_time = datetime.now(timezone.utc)
        self.logger = logger.bind(component="HealthChecker")

    def register_check(self, health_check: HealthCheck) -> None:
        """Register a health check.

        Args:
            health_check: Health check to register
        """
        self.health_checks[health_check.name] = health_check
        self.logger.info(f"Health check registered: {health_check.name}")

    def unregister_check(self, name: str) -> None:
        """Unregister a health check.

        Args:
            name: Name of the health check to remove
        """
        if name in self.health_checks:
            del self.health_checks[name]
            self.logger.info(f"Health check unregistered: {name}")

    async def start(self) -> None:
        """Start the health checking loop."""
        if self.running:
            self.logger.warning("Health checker is already running")
            return

        self.running = True
        self.check_task = asyncio.create_task(self._health_check_loop())
        self.logger.info("Health checker started")

    async def stop(self) -> None:
        """Stop the health checking loop."""
        if not self.running:
            return

        self.running = False
        if self.check_task:
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass

        self.logger.info("Health checker stopped")

    async def check_all(self) -> Dict[str, Any]:
        """Execute all health checks immediately.

        Returns:
            Dictionary with overall health status and individual check results
        """
        if not self.health_checks:
            return {
                "overall_status": HealthStatus.HEALTHY.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "uptime_seconds": (
                    datetime.now(timezone.utc) - self.start_time
                ).total_seconds(),
                "checks": {},
                "summary": {
                    "total_checks": 0,
                    "healthy_checks": 0,
                    "degraded_checks": 0,
                    "unhealthy_checks": 0,
                    "unknown_checks": 0,
                },
            }

        # Execute all checks concurrently
        check_tasks = [
            self._execute_single_check(name, check)
            for name, check in self.health_checks.items()
        ]

        check_results = await asyncio.gather(*check_tasks, return_exceptions=True)

        # Compile results
        checks_info = {}
        status_counts = {status: 0 for status in HealthStatus}

        for (name, check), result in zip(self.health_checks.items(), check_results):
            check_info = check.get_status_info()
            checks_info[name] = check_info
            status_counts[check.status] += 1

        # Determine overall status
        overall_status = self._calculate_overall_status(status_counts)

        return {
            "overall_status": overall_status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": (
                datetime.now(timezone.utc) - self.start_time
            ).total_seconds(),
            "checks": checks_info,
            "summary": {
                "total_checks": len(self.health_checks),
                "healthy_checks": status_counts[HealthStatus.HEALTHY],
                "degraded_checks": status_counts[HealthStatus.DEGRADED],
                "unhealthy_checks": status_counts[HealthStatus.UNHEALTHY],
                "unknown_checks": status_counts[HealthStatus.UNKNOWN],
            },
        }

    async def get_check_status(self, name: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific health check.

        Args:
            name: Name of the health check

        Returns:
            Health check status info or None if not found
        """
        if name not in self.health_checks:
            return None

        return self.health_checks[name].get_status_info()

    async def _health_check_loop(self) -> None:
        """Main health checking loop."""
        while self.running:
            try:
                # Calculate next check times
                next_checks = {}
                current_time = datetime.now(timezone.utc)

                for name, check in self.health_checks.items():
                    if check.last_check_time is None:
                        # First check - execute immediately
                        next_checks[name] = current_time
                    else:
                        # Calculate next check time based on interval
                        next_check_time = check.last_check_time + timedelta(
                            seconds=check.interval_seconds
                        )
                        next_checks[name] = next_check_time

                # Find checks that need to be executed
                checks_to_execute = []
                for name, next_check_time in next_checks.items():
                    if current_time >= next_check_time:
                        checks_to_execute.append(name)

                # Execute checks
                if checks_to_execute:
                    check_tasks = [
                        self._execute_single_check(name, self.health_checks[name])
                        for name in checks_to_execute
                    ]
                    await asyncio.gather(*check_tasks, return_exceptions=True)

                # Sleep for a short interval before next iteration
                await asyncio.sleep(1.0)

            except Exception as e:
                self.logger.error(f"Error in health check loop: {str(e)}")
                await asyncio.sleep(5.0)  # Wait longer on error

    async def _execute_single_check(self, name: str, check: HealthCheck) -> None:
        """Execute a single health check.

        Args:
            name: Name of the health check
            check: Health check instance
        """
        try:
            await check.execute_check()
        except Exception as e:
            self.logger.error(
                f"Unexpected error executing health check {name}: {str(e)}"
            )

    def _calculate_overall_status(
        self, status_counts: Dict[HealthStatus, int]
    ) -> HealthStatus:
        """Calculate overall health status from individual check statuses.

        Args:
            status_counts: Count of checks in each status

        Returns:
            Overall health status
        """
        # If any checks are unhealthy, overall is unhealthy
        if status_counts[HealthStatus.UNHEALTHY] > 0:
            return HealthStatus.UNHEALTHY

        # If any checks are degraded, overall is degraded
        if status_counts[HealthStatus.DEGRADED] > 0:
            return HealthStatus.DEGRADED

        # If any checks are unknown, overall is degraded
        if status_counts[HealthStatus.UNKNOWN] > 0:
            return HealthStatus.DEGRADED

        # All checks are healthy
        return HealthStatus.HEALTHY

    def create_database_check(
        self, connection_test_func: Callable[[], Awaitable[bool]]
    ) -> HealthCheck:
        """Create a database connectivity health check.

        Args:
            connection_test_func: Function to test database connectivity

        Returns:
            Database health check
        """
        return HealthCheck(
            name="database",
            check_function=connection_test_func,
            timeout_seconds=5.0,
            interval_seconds=30.0,
            failure_threshold=3,
            success_threshold=1,
        )

    def create_redis_check(self, redis_client) -> HealthCheck:
        """Create a Redis connectivity health check.

        Args:
            redis_client: Redis client instance

        Returns:
            Redis health check
        """

        async def redis_ping():
            try:
                if hasattr(redis_client, "ping"):
                    return redis_client.ping()
                return False
            except Exception:
                return False

        return HealthCheck(
            name="redis",
            check_function=redis_ping,
            timeout_seconds=3.0,
            interval_seconds=15.0,
            failure_threshold=2,
            success_threshold=1,
        )

    def create_mlflow_check(self, mlflow_client) -> HealthCheck:
        """Create an MLflow connectivity health check.

        Args:
            mlflow_client: MLflow client instance

        Returns:
            MLflow health check
        """

        async def mlflow_ping():
            try:
                # Test by listing experiments
                mlflow_client.list_experiments(max_results=1)
                return True
            except Exception:
                return False

        return HealthCheck(
            name="mlflow",
            check_function=mlflow_ping,
            timeout_seconds=10.0,
            interval_seconds=60.0,
            failure_threshold=3,
            success_threshold=1,
        )

    def create_memory_check(self, max_memory_mb: float) -> HealthCheck:
        """Create a memory usage health check.

        Args:
            max_memory_mb: Maximum allowed memory usage in MB

        Returns:
            Memory health check
        """

        async def memory_check():
            try:
                import psutil

                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                return memory_mb <= max_memory_mb
            except Exception:
                return False

        return HealthCheck(
            name="memory",
            check_function=memory_check,
            timeout_seconds=2.0,
            interval_seconds=30.0,
            failure_threshold=5,
            success_threshold=2,
        )
