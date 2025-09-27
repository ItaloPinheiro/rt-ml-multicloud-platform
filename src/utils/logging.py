"""Logging utilities for structured logging across the application."""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

try:
    import structlog
    from structlog.stdlib import LoggerFactory, add_log_level, filter_by_level
    from structlog.processors import JSONRenderer, TimeStamper, add_log_level, CallsiteParameterAdder
except ImportError:
    structlog = None

try:
    from pythonjsonlogger import jsonlogger
except ImportError:
    jsonlogger = None


class CustomJSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON formatted log string
        """
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in log_data and not key.startswith('_'):
                if key in ['args', 'asctime', 'created', 'filename', 'levelno',
                          'lineno', 'module', 'msecs', 'msg', 'name', 'pathname',
                          'process', 'processName', 'relativeCreated', 'thread',
                          'threadName', 'funcName', 'getMessage', 'exc_info', 'exc_text', 'stack_info']:
                    continue
                try:
                    json.dumps(value)  # Test if value is JSON serializable
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data, default=str)


def setup_logging(
    level: str = "INFO",
    format_type: str = "structured",
    log_file: Optional[str] = None,
    enable_console: bool = True,
    service_name: str = "ml-pipeline",
    environment: str = "development"
) -> None:
    """Setup application logging.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: Logging format (structured, json, simple)
        log_file: Optional log file path
        enable_console: Whether to enable console logging
        service_name: Service name for log context
        environment: Environment name for log context
    """
    # Configure standard library logging
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Configure structlog if available
    if structlog is not None and format_type == "structured":
        configure_structlog(level, log_file, enable_console, service_name, environment)
    else:
        configure_standard_logging(level, format_type, log_file, enable_console, service_name, environment)


def configure_structlog(
    level: str,
    log_file: Optional[str],
    enable_console: bool,
    service_name: str,
    environment: str
) -> None:
    """Configure structlog for structured logging.

    Args:
        level: Logging level
        log_file: Optional log file path
        enable_console: Whether to enable console logging
        service_name: Service name for log context
        environment: Environment name for log context
    """
    processors = [
        filter_by_level,
        add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Add call site information in development
    if environment == "development":
        processors.append(CallsiteParameterAdder())

    # Choose renderer based on environment
    if environment == "production":
        processors.append(JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logger
    formatter = CustomJSONFormatter() if environment == "production" else None

    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        if formatter:
            console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, level.upper()))
        logging.getLogger().addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        if formatter:
            file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, level.upper()))
        logging.getLogger().addHandler(file_handler)

    # Add global context
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        service=service_name,
        environment=environment,
        version=os.getenv("VERSION", "unknown")
    )


def configure_standard_logging(
    level: str,
    format_type: str,
    log_file: Optional[str],
    enable_console: bool,
    service_name: str,
    environment: str
) -> None:
    """Configure standard library logging.

    Args:
        level: Logging level
        format_type: Logging format type
        log_file: Optional log file path
        enable_console: Whether to enable console logging
        service_name: Service name for log context
        environment: Environment name for log context
    """
    # Choose formatter based on format type
    if format_type == "json" and jsonlogger is not None:
        formatter = jsonlogger.JsonFormatter(
            '%(asctime)s %(name)s %(levelname)s %(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S'
        )
    elif format_type == "json":
        formatter = CustomJSONFormatter()
    else:
        # Simple format
        formatter = logging.Formatter(
            f'%(asctime)s - {service_name} - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, level.upper()))
        logging.getLogger().addHandler(console_handler)

    # File handler
    if log_file:
        # Create log directory if it doesn't exist
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, level.upper()))
        logging.getLogger().addHandler(file_handler)


def get_logger(name: str) -> Any:
    """Get a logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance (structlog or standard logger)
    """
    if structlog is not None:
        return structlog.get_logger(name)
    else:
        return logging.getLogger(name)


def log_function_call(func):
    """Decorator to log function calls with arguments and timing.

    Args:
        func: Function to decorate

    Returns:
        Decorated function
    """
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)

        # Log function entry
        logger.debug(
            "Function called",
            function=func.__name__,
            module=func.__module__,
            args_count=len(args),
            kwargs_keys=list(kwargs.keys())
        )

        start_time = datetime.utcnow()

        try:
            result = func(*args, **kwargs)

            # Log successful completion
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            logger.debug(
                "Function completed successfully",
                function=func.__name__,
                duration_seconds=duration
            )

            return result

        except Exception as e:
            # Log exception
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            logger.error(
                "Function failed with exception",
                function=func.__name__,
                duration_seconds=duration,
                error=str(e),
                exception_type=type(e).__name__
            )

            raise

    return wrapper


def log_performance(operation: str):
    """Decorator to log performance metrics for operations.

    Args:
        operation: Name of the operation being measured

    Returns:
        Decorator function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)

            start_time = datetime.utcnow()

            try:
                result = func(*args, **kwargs)

                end_time = datetime.utcnow()
                duration = (end_time - start_time).total_seconds()

                logger.info(
                    "Performance metric",
                    operation=operation,
                    function=func.__name__,
                    duration_seconds=duration,
                    status="success"
                )

                return result

            except Exception as e:
                end_time = datetime.utcnow()
                duration = (end_time - start_time).total_seconds()

                logger.warning(
                    "Performance metric",
                    operation=operation,
                    function=func.__name__,
                    duration_seconds=duration,
                    status="error",
                    error=str(e)
                )

                raise

        return wrapper
    return decorator


class LogContext:
    """Context manager for adding structured logging context."""

    def __init__(self, **context):
        """Initialize log context.

        Args:
            **context: Context variables to add
        """
        self.context = context
        self.old_context = {}

    def __enter__(self):
        """Enter context and bind variables."""
        if structlog is not None:
            # Store old context
            current_context = structlog.contextvars.get_contextvars()
            self.old_context = current_context.copy()

            # Bind new context
            structlog.contextvars.bind_contextvars(**self.context)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and restore previous context."""
        if structlog is not None:
            # Clear current context
            structlog.contextvars.clear_contextvars()

            # Restore old context
            if self.old_context:
                structlog.contextvars.bind_contextvars(**self.old_context)


def setup_request_logging():
    """Setup request-specific logging for web applications."""
    try:
        import uuid
        from contextvars import ContextVar

        # Create context variable for request ID
        request_id_var: ContextVar[str] = ContextVar('request_id', default='')

        def add_request_id(logger, method_name, event_dict):
            """Add request ID to log events."""
            request_id = request_id_var.get('')
            if request_id:
                event_dict['request_id'] = request_id
            return event_dict

        # Add processor if using structlog
        if structlog is not None:
            structlog.configure(
                processors=structlog.get_config()["processors"] + [add_request_id]
            )

        return request_id_var

    except ImportError:
        # Fall back to thread-local storage
        import threading

        request_context = threading.local()

        def add_request_id(logger, method_name, event_dict):
            """Add request ID to log events."""
            request_id = getattr(request_context, 'request_id', '')
            if request_id:
                event_dict['request_id'] = request_id
            return event_dict

        if structlog is not None:
            structlog.configure(
                processors=structlog.get_config()["processors"] + [add_request_id]
            )

        return request_context


def configure_ml_pipeline_logging(
    environment: str = "development",
    service_name: str = "ml-pipeline"
) -> None:
    """Configure logging specifically for ML pipeline services.

    Args:
        environment: Environment name
        service_name: Service name
    """
    # Determine log level based on environment
    log_level = "DEBUG" if environment == "development" else "INFO"

    # Setup logging
    setup_logging(
        level=log_level,
        format_type="structured" if structlog else "json",
        log_file=f"logs/{service_name}.log" if environment != "development" else None,
        enable_console=True,
        service_name=service_name,
        environment=environment
    )

    # Configure specific loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("apache_beam").setLevel(logging.WARNING)

    # Set MLflow logging to WARNING to reduce noise
    logging.getLogger("mlflow").setLevel(logging.WARNING)

    logger = get_logger(__name__)
    logger.info(
        "Logging configured",
        environment=environment,
        service=service_name,
        level=log_level
    )