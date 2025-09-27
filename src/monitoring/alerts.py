"""Alert management and notification system for ML pipeline monitoring."""

import asyncio
import smtplib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Set
from enum import Enum
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import structlog

logger = structlog.get_logger()


class AlertSeverity(Enum):
    """Alert severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(Enum):
    """Alert status."""
    ACTIVE = "active"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class Alert:
    """Individual alert definition."""

    def __init__(
        self,
        name: str,
        description: str,
        severity: AlertSeverity,
        condition_func: Callable[[Dict[str, Any]], bool],
        cooldown_minutes: int = 15,
        auto_resolve: bool = True,
        tags: Optional[Dict[str, str]] = None
    ):
        """Initialize alert.

        Args:
            name: Alert name
            description: Alert description
            severity: Alert severity level
            condition_func: Function that returns True when alert should trigger
            cooldown_minutes: Minimum time between alert notifications
            auto_resolve: Whether alert auto-resolves when condition is false
            tags: Optional tags for alert categorization
        """
        self.name = name
        self.description = description
        self.severity = severity
        self.condition_func = condition_func
        self.cooldown_minutes = cooldown_minutes
        self.auto_resolve = auto_resolve
        self.tags = tags or {}

        # State tracking
        self.status = AlertStatus.RESOLVED
        self.first_triggered_time: Optional[datetime] = None
        self.last_triggered_time: Optional[datetime] = None
        self.last_notified_time: Optional[datetime] = None
        self.resolved_time: Optional[datetime] = None
        self.trigger_count = 0
        self.current_context: Optional[Dict[str, Any]] = None

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate alert condition.

        Args:
            context: Context data for alert evaluation

        Returns:
            True if alert condition is met
        """
        try:
            condition_met = self.condition_func(context)
            current_time = datetime.utcnow()

            if condition_met:
                if self.status == AlertStatus.RESOLVED:
                    # Alert is triggering for the first time or after resolution
                    self.status = AlertStatus.ACTIVE
                    self.first_triggered_time = current_time
                    self.trigger_count = 1
                    self.resolved_time = None
                else:
                    # Alert is still active
                    self.trigger_count += 1

                self.last_triggered_time = current_time
                self.current_context = context
                return True

            else:
                # Condition not met
                if self.status == AlertStatus.ACTIVE and self.auto_resolve:
                    # Auto-resolve the alert
                    self.status = AlertStatus.RESOLVED
                    self.resolved_time = current_time
                    self.current_context = None

                return False

        except Exception as e:
            logger.error(f"Error evaluating alert {self.name}: {str(e)}")
            return False

    def should_notify(self) -> bool:
        """Check if alert should send notification.

        Returns:
            True if notification should be sent
        """
        if self.status != AlertStatus.ACTIVE:
            return False

        if self.last_notified_time is None:
            return True

        # Check cooldown period
        cooldown_deadline = self.last_notified_time + timedelta(minutes=self.cooldown_minutes)
        return datetime.utcnow() >= cooldown_deadline

    def mark_notified(self) -> None:
        """Mark alert as notified."""
        self.last_notified_time = datetime.utcnow()

    def suppress(self) -> None:
        """Suppress alert notifications."""
        self.status = AlertStatus.SUPPRESSED

    def unsuppress(self) -> None:
        """Remove alert suppression."""
        if self.status == AlertStatus.SUPPRESSED:
            self.status = AlertStatus.RESOLVED

    def get_info(self) -> Dict[str, Any]:
        """Get alert information.

        Returns:
            Dictionary with alert details
        """
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity.value,
            "status": self.status.value,
            "first_triggered_time": self.first_triggered_time.isoformat() if self.first_triggered_time else None,
            "last_triggered_time": self.last_triggered_time.isoformat() if self.last_triggered_time else None,
            "last_notified_time": self.last_notified_time.isoformat() if self.last_notified_time else None,
            "resolved_time": self.resolved_time.isoformat() if self.resolved_time else None,
            "trigger_count": self.trigger_count,
            "cooldown_minutes": self.cooldown_minutes,
            "auto_resolve": self.auto_resolve,
            "tags": self.tags,
            "current_context": self.current_context
        }


class NotificationChannel:
    """Base class for notification channels."""

    async def send_notification(self, alert: Alert, message: str) -> bool:
        """Send notification for an alert.

        Args:
            alert: Alert instance
            message: Notification message

        Returns:
            True if notification was sent successfully
        """
        raise NotImplementedError


class EmailNotificationChannel(NotificationChannel):
    """Email notification channel."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        to_emails: List[str],
        use_tls: bool = True
    ):
        """Initialize email notification channel.

        Args:
            smtp_host: SMTP server host
            smtp_port: SMTP server port
            username: SMTP username
            password: SMTP password
            from_email: From email address
            to_emails: List of recipient email addresses
            use_tls: Whether to use TLS
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_emails = to_emails
        self.use_tls = use_tls

    async def send_notification(self, alert: Alert, message: str) -> bool:
        """Send email notification.

        Args:
            alert: Alert instance
            message: Notification message

        Returns:
            True if email was sent successfully
        """
        try:
            # Create message
            msg = MimeMultipart()
            msg['From'] = self.from_email
            msg['To'] = ', '.join(self.to_emails)
            msg['Subject'] = f"[{alert.severity.value.upper()}] {alert.name}"

            # Create HTML and text versions
            html_message = self._create_html_message(alert, message)
            text_message = self._create_text_message(alert, message)

            msg.attach(MimeText(text_message, 'plain'))
            msg.attach(MimeText(html_message, 'html'))

            # Send email
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            if self.use_tls:
                server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()

            return True

        except Exception as e:
            logger.error(f"Failed to send email notification: {str(e)}")
            return False

    def _create_html_message(self, alert: Alert, message: str) -> str:
        """Create HTML email message.

        Args:
            alert: Alert instance
            message: Base message

        Returns:
            HTML formatted message
        """
        severity_colors = {
            AlertSeverity.LOW: "#28a745",
            AlertSeverity.MEDIUM: "#ffc107",
            AlertSeverity.HIGH: "#fd7e14",
            AlertSeverity.CRITICAL: "#dc3545"
        }

        color = severity_colors.get(alert.severity, "#6c757d")

        html = f"""
        <html>
        <body>
            <h2 style="color: {color};">[{alert.severity.value.upper()}] {alert.name}</h2>
            <p><strong>Description:</strong> {alert.description}</p>
            <p><strong>Status:</strong> {alert.status.value}</p>
            <p><strong>Triggered Time:</strong> {alert.last_triggered_time.strftime('%Y-%m-%d %H:%M:%S UTC') if alert.last_triggered_time else 'N/A'}</p>
            <p><strong>Trigger Count:</strong> {alert.trigger_count}</p>

            <h3>Details:</h3>
            <p>{message}</p>

            {self._format_context_html(alert.current_context) if alert.current_context else ''}

            <hr>
            <p><small>Generated by ML Pipeline Alert System</small></p>
        </body>
        </html>
        """
        return html

    def _create_text_message(self, alert: Alert, message: str) -> str:
        """Create plain text email message.

        Args:
            alert: Alert instance
            message: Base message

        Returns:
            Plain text message
        """
        text = f"""
[{alert.severity.value.upper()}] {alert.name}

Description: {alert.description}
Status: {alert.status.value}
Triggered Time: {alert.last_triggered_time.strftime('%Y-%m-%d %H:%M:%S UTC') if alert.last_triggered_time else 'N/A'}
Trigger Count: {alert.trigger_count}

Details:
{message}

{self._format_context_text(alert.current_context) if alert.current_context else ''}

---
Generated by ML Pipeline Alert System
        """
        return text.strip()

    def _format_context_html(self, context: Dict[str, Any]) -> str:
        """Format context data as HTML.

        Args:
            context: Context dictionary

        Returns:
            HTML formatted context
        """
        html = "<h3>Context:</h3><ul>"
        for key, value in context.items():
            html += f"<li><strong>{key}:</strong> {value}</li>"
        html += "</ul>"
        return html

    def _format_context_text(self, context: Dict[str, Any]) -> str:
        """Format context data as plain text.

        Args:
            context: Context dictionary

        Returns:
            Plain text formatted context
        """
        text = "Context:\n"
        for key, value in context.items():
            text += f"  {key}: {value}\n"
        return text


class LogNotificationChannel(NotificationChannel):
    """Log-based notification channel."""

    def __init__(self, logger_instance: Optional[Any] = None):
        """Initialize log notification channel.

        Args:
            logger_instance: Optional logger instance
        """
        self.logger = logger_instance or logger

    async def send_notification(self, alert: Alert, message: str) -> bool:
        """Send log notification.

        Args:
            alert: Alert instance
            message: Notification message

        Returns:
            Always returns True
        """
        log_level = {
            AlertSeverity.LOW: "info",
            AlertSeverity.MEDIUM: "warning",
            AlertSeverity.HIGH: "error",
            AlertSeverity.CRITICAL: "critical"
        }.get(alert.severity, "info")

        getattr(self.logger, log_level)(
            f"ALERT [{alert.severity.value.upper()}] {alert.name}: {message}",
            alert_name=alert.name,
            alert_severity=alert.severity.value,
            alert_status=alert.status.value,
            trigger_count=alert.trigger_count,
            context=alert.current_context
        )

        return True


class AlertManager:
    """Central alert management system."""

    def __init__(self, evaluation_interval_seconds: float = 60.0):
        """Initialize alert manager.

        Args:
            evaluation_interval_seconds: Interval between alert evaluations
        """
        self.alerts: Dict[str, Alert] = {}
        self.notification_channels: List[NotificationChannel] = []
        self.evaluation_interval_seconds = evaluation_interval_seconds
        self.running = False
        self.evaluation_task: Optional[asyncio.Task] = None
        self.suppressed_alerts: Set[str] = set()
        self.logger = logger.bind(component="AlertManager")

    def register_alert(self, alert: Alert) -> None:
        """Register an alert.

        Args:
            alert: Alert to register
        """
        self.alerts[alert.name] = alert
        self.logger.info(f"Alert registered: {alert.name}")

    def unregister_alert(self, name: str) -> None:
        """Unregister an alert.

        Args:
            name: Name of alert to remove
        """
        if name in self.alerts:
            del self.alerts[name]
            self.suppressed_alerts.discard(name)
            self.logger.info(f"Alert unregistered: {name}")

    def add_notification_channel(self, channel: NotificationChannel) -> None:
        """Add a notification channel.

        Args:
            channel: Notification channel to add
        """
        self.notification_channels.append(channel)
        self.logger.info(f"Notification channel added: {type(channel).__name__}")

    async def start(self) -> None:
        """Start the alert evaluation loop."""
        if self.running:
            self.logger.warning("Alert manager is already running")
            return

        self.running = True
        self.evaluation_task = asyncio.create_task(self._evaluation_loop())
        self.logger.info("Alert manager started")

    async def stop(self) -> None:
        """Stop the alert evaluation loop."""
        if not self.running:
            return

        self.running = False
        if self.evaluation_task:
            self.evaluation_task.cancel()
            try:
                await self.evaluation_task
            except asyncio.CancelledError:
                pass

        self.logger.info("Alert manager stopped")

    async def evaluate_alerts(self, context: Dict[str, Any]) -> List[Alert]:
        """Evaluate all alerts with given context.

        Args:
            context: Context data for alert evaluation

        Returns:
            List of triggered alerts
        """
        triggered_alerts = []

        for alert in self.alerts.values():
            if alert.name in self.suppressed_alerts:
                continue

            try:
                if alert.evaluate(context):
                    triggered_alerts.append(alert)

                    # Send notifications if needed
                    if alert.should_notify():
                        await self._send_notifications(alert)
                        alert.mark_notified()

            except Exception as e:
                self.logger.error(f"Error evaluating alert {alert.name}: {str(e)}")

        return triggered_alerts

    def suppress_alert(self, name: str) -> bool:
        """Suppress an alert.

        Args:
            name: Name of alert to suppress

        Returns:
            True if alert was suppressed
        """
        if name in self.alerts:
            self.suppressed_alerts.add(name)
            self.alerts[name].suppress()
            self.logger.info(f"Alert suppressed: {name}")
            return True
        return False

    def unsuppress_alert(self, name: str) -> bool:
        """Remove suppression from an alert.

        Args:
            name: Name of alert to unsuppress

        Returns:
            True if alert was unsuppressed
        """
        if name in self.alerts:
            self.suppressed_alerts.discard(name)
            self.alerts[name].unsuppress()
            self.logger.info(f"Alert unsuppressed: {name}")
            return True
        return False

    def get_alert_status(self) -> Dict[str, Any]:
        """Get status of all alerts.

        Returns:
            Dictionary with alert status information
        """
        active_alerts = [alert for alert in self.alerts.values() if alert.status == AlertStatus.ACTIVE]
        suppressed_alerts = [alert for alert in self.alerts.values() if alert.status == AlertStatus.SUPPRESSED]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_alerts": len(self.alerts),
            "active_alerts": len(active_alerts),
            "suppressed_alerts": len(suppressed_alerts),
            "alerts": {name: alert.get_info() for name, alert in self.alerts.items()}
        }

    async def _evaluation_loop(self) -> None:
        """Main alert evaluation loop."""
        while self.running:
            try:
                # This is a basic evaluation loop - in practice, you would
                # gather context from various monitoring sources
                context = await self._gather_context()
                await self.evaluate_alerts(context)

                await asyncio.sleep(self.evaluation_interval_seconds)

            except Exception as e:
                self.logger.error(f"Error in alert evaluation loop: {str(e)}")
                await asyncio.sleep(10.0)  # Wait longer on error

    async def _gather_context(self) -> Dict[str, Any]:
        """Gather context data for alert evaluation.

        Returns:
            Context dictionary
        """
        # This is a placeholder - implement actual context gathering
        # from metrics, health checks, logs, etc.
        return {
            "timestamp": datetime.utcnow(),
            "system_metrics": {},
            "application_metrics": {},
            "health_status": {}
        }

    async def _send_notifications(self, alert: Alert) -> None:
        """Send notifications for an alert.

        Args:
            alert: Alert to send notifications for
        """
        message = f"{alert.description}"
        if alert.current_context:
            message += f"\n\nContext: {alert.current_context}"

        notification_tasks = [
            channel.send_notification(alert, message)
            for channel in self.notification_channels
        ]

        if notification_tasks:
            results = await asyncio.gather(*notification_tasks, return_exceptions=True)

            success_count = sum(1 for result in results if result is True)
            self.logger.info(
                f"Sent notifications for alert {alert.name}",
                channels_attempted=len(notification_tasks),
                channels_successful=success_count
            )

    def create_prediction_latency_alert(self, threshold_seconds: float) -> Alert:
        """Create an alert for high prediction latency.

        Args:
            threshold_seconds: Latency threshold in seconds

        Returns:
            Prediction latency alert
        """
        def condition(context: Dict[str, Any]) -> bool:
            metrics = context.get("application_metrics", {})
            avg_latency = metrics.get("avg_prediction_latency_seconds", 0)
            return avg_latency > threshold_seconds

        return Alert(
            name="high_prediction_latency",
            description=f"Average prediction latency exceeded {threshold_seconds}s",
            severity=AlertSeverity.HIGH,
            condition_func=condition,
            cooldown_minutes=10,
            tags={"component": "prediction", "type": "performance"}
        )

    def create_error_rate_alert(self, threshold_percent: float) -> Alert:
        """Create an alert for high error rate.

        Args:
            threshold_percent: Error rate threshold percentage

        Returns:
            Error rate alert
        """
        def condition(context: Dict[str, Any]) -> bool:
            metrics = context.get("application_metrics", {})
            error_rate = metrics.get("error_rate_percent", 0)
            return error_rate > threshold_percent

        return Alert(
            name="high_error_rate",
            description=f"Error rate exceeded {threshold_percent}%",
            severity=AlertSeverity.CRITICAL,
            condition_func=condition,
            cooldown_minutes=5,
            tags={"component": "api", "type": "reliability"}
        )