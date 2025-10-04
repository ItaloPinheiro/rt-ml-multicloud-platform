"""Database session management and connection utilities."""

import os
from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import structlog

from ..utils.config import get_config, DatabaseConfig

logger = structlog.get_logger()


class DatabaseManager:
    """Database connection and session management."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        """Initialize database manager.

        Args:
            config: Database configuration. If None, will load from environment.
        """
        if config is None:
            app_config = get_config()
            config = app_config.database

        if config is None:
            raise ValueError("Database configuration is required")

        self.config = config
        self.engine: Optional[Engine] = None
        self.session_factory: Optional[sessionmaker] = None
        self.logger = logger.bind(component="DatabaseManager")

    def initialize(self) -> None:
        """Initialize database engine and session factory."""
        try:
            # Build connection URL
            connection_url = self._build_connection_url()

            # Handle SQLite special case first
            if connection_url.startswith("sqlite"):
                engine_kwargs = {
                    "echo": False,  # Set to True for SQL debugging
                    "poolclass": StaticPool,
                    "connect_args": {"check_same_thread": False}
                }
            else:
                # Create engine with connection pooling for non-SQLite databases
                engine_kwargs = {
                    "echo": False,  # Set to True for SQL debugging
                    "pool_pre_ping": True,
                    "pool_recycle": 3600,
                    "pool_size": min(self.config.max_connections, 20),
                    "max_overflow": 10,
                    "connect_args": {
                        "connect_timeout": self.config.connection_timeout,
                        "sslmode": self.config.ssl_mode,
                    }
                }

            self.engine = create_engine(connection_url, **engine_kwargs)

            # Add connection event listeners
            self._setup_event_listeners()

            # Create session factory
            self.session_factory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False
            )

            self.logger.info(
                "Database manager initialized",
                host=self.config.host,
                port=self.config.port,
                database=self.config.database
            )

        except Exception as e:
            self.logger.error("Failed to initialize database manager", error=str(e))
            raise

    def _build_connection_url(self) -> str:
        """Build database connection URL.

        Returns:
            Database connection URL
        """
        # Handle different database types
        if self.config.host == "sqlite" or self.config.database.endswith(".db"):
            return f"sqlite:///{self.config.database}"

        # PostgreSQL connection URL
        username = self.config.username
        password = self.config.password
        host = self.config.host
        port = self.config.port
        database = self.config.database

        return f"postgresql://{username}:{password}@{host}:{port}/{database}"

    def _setup_event_listeners(self) -> None:
        """Setup SQLAlchemy event listeners for monitoring."""

        @event.listens_for(self.engine, "connect")
        def on_connect(dbapi_connection, connection_record):
            """Handle new database connections."""
            self.logger.debug("New database connection established")

        @event.listens_for(self.engine, "checkout")
        def on_checkout(dbapi_connection, connection_record, connection_proxy):
            """Handle connection checkout from pool."""
            self.logger.debug("Connection checked out from pool")

        @event.listens_for(self.engine, "checkin")
        def on_checkin(dbapi_connection, connection_record):
            """Handle connection checkin to pool."""
            self.logger.debug("Connection checked in to pool")

        @event.listens_for(self.engine, "invalidate")
        def on_invalidate(dbapi_connection, connection_record, exception):
            """Handle connection invalidation."""
            self.logger.warning(
                "Database connection invalidated",
                error=str(exception) if exception else "Unknown"
            )

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get database session with automatic cleanup.

        Yields:
            SQLAlchemy session

        Raises:
            RuntimeError: If database manager is not initialized
        """
        if self.session_factory is None:
            raise RuntimeError("Database manager not initialized. Call initialize() first.")

        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_tables(self) -> None:
        """Create all database tables."""
        if self.engine is None:
            raise RuntimeError("Database manager not initialized")

        try:
            from .models import Base
            Base.metadata.create_all(bind=self.engine)
            self.logger.info("Database tables created successfully")
        except Exception as e:
            self.logger.error("Failed to create database tables", error=str(e))
            raise

    def drop_tables(self) -> None:
        """Drop all database tables."""
        if self.engine is None:
            raise RuntimeError("Database manager not initialized")

        try:
            from .models import Base
            Base.metadata.drop_all(bind=self.engine)
            self.logger.info("Database tables dropped successfully")
        except Exception as e:
            self.logger.error("Failed to drop database tables", error=str(e))
            raise

    def check_connection(self) -> bool:
        """Check database connectivity.

        Returns:
            True if connection is successful, False otherwise
        """
        if self.engine is None:
            return False

        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception as e:
            self.logger.error("Database connection check failed", error=str(e))
            return False

    def get_connection_info(self) -> dict:
        """Get connection pool information.

        Returns:
            Dictionary with connection pool stats
        """
        if self.engine is None:
            return {}

        pool = self.engine.pool
        info = {}

        # Try to get pool stats - some methods may not be available for all pool types
        try:
            info["pool_size"] = pool.size()
        except (AttributeError, NotImplementedError):
            info["pool_size"] = None

        try:
            info["checked_in"] = pool.checkedin()
        except (AttributeError, NotImplementedError):
            info["checked_in"] = None

        try:
            info["checked_out"] = pool.checkedout()
        except (AttributeError, NotImplementedError):
            info["checked_out"] = None

        try:
            info["overflow"] = pool.overflow()
        except (AttributeError, NotImplementedError):
            info["overflow"] = None

        try:
            info["invalid"] = pool.invalid()
        except (AttributeError, NotImplementedError):
            info["invalid"] = None

        return info

    def close(self) -> None:
        """Close database connections and cleanup resources."""
        if self.engine:
            self.engine.dispose()
            self.logger.info("Database connections closed")


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def initialize_database(config: Optional[DatabaseConfig] = None) -> DatabaseManager:
    """Initialize global database manager.

    Args:
        config: Database configuration

    Returns:
        Initialized database manager
    """
    global _db_manager

    _db_manager = DatabaseManager(config)
    _db_manager.initialize()

    return _db_manager


def get_database_manager() -> DatabaseManager:
    """Get global database manager instance.

    Returns:
        Database manager instance

    Raises:
        RuntimeError: If database manager is not initialized
    """
    if _db_manager is None:
        raise RuntimeError("Database manager not initialized. Call initialize_database() first.")

    return _db_manager


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get database session from global manager.

    Yields:
        SQLAlchemy session
    """
    db_manager = get_database_manager()
    with db_manager.get_session() as session:
        yield session


# Compatibility alias for legacy code
get_db_session = get_session


def create_test_database() -> DatabaseManager:
    """Create in-memory database for testing.

    Returns:
        Database manager with in-memory SQLite
    """
    from ..utils.config import DatabaseConfig

    test_config = DatabaseConfig(
        host="sqlite",
        port=0,
        database=":memory:",
        username="",
        password="",
        ssl_mode="disable"
    )

    db_manager = DatabaseManager(test_config)
    db_manager.initialize()
    db_manager.create_tables()

    return db_manager