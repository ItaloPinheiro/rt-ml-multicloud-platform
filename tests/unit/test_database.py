"""Unit tests for database models and session management."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError

from src.database.models import (
    Experiment, ModelRun, FeatureStore, PredictionLog, DataDriftMonitoring
)
from src.database.session import DatabaseManager, get_session, create_test_database


class TestDatabaseModels:
    """Test database model functionality."""

    def test_experiment_creation(self, db_session):
        """Test experiment model creation."""
        experiment = Experiment(
            name="test_experiment",
            description="Test experiment description",
            tags={"version": "1.0", "type": "classification"}
        )

        db_session.add(experiment)
        db_session.commit()

        # Verify experiment was created
        retrieved = db_session.query(Experiment).filter_by(name="test_experiment").first()
        assert retrieved is not None
        assert retrieved.name == "test_experiment"
        assert retrieved.description == "Test experiment description"
        assert retrieved.tags["version"] == "1.0"
        assert retrieved.is_active is True

    def test_experiment_unique_name(self, db_session):
        """Test experiment name uniqueness constraint."""
        # Create first experiment
        exp1 = Experiment(name="duplicate_name")
        db_session.add(exp1)
        db_session.commit()

        # Try to create second experiment with same name
        exp2 = Experiment(name="duplicate_name")
        db_session.add(exp2)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_model_run_creation(self, db_session):
        """Test model run creation."""
        # Create experiment first
        experiment = Experiment(name="test_experiment")
        db_session.add(experiment)
        db_session.commit()

        # Create model run
        model_run = ModelRun(
            experiment_id=experiment.id,
            run_name="test_run",
            model_name="fraud_detector",
            model_version="1.0",
            status="FINISHED",
            parameters={"learning_rate": 0.01, "max_depth": 5},
            metrics={"accuracy": 0.95, "precision": 0.92},
            tags={"framework": "sklearn"},
            model_type="classification",
            framework="sklearn",
            training_data_size=10000,
            validation_score=0.93
        )

        db_session.add(model_run)
        db_session.commit()

        # Verify model run was created
        retrieved = db_session.query(ModelRun).filter_by(run_name="test_run").first()
        assert retrieved is not None
        assert retrieved.model_name == "fraud_detector"
        assert retrieved.parameters["learning_rate"] == 0.01
        assert retrieved.metrics["accuracy"] == 0.95

    def test_model_run_status_validation(self, db_session):
        """Test model run status validation."""
        experiment = Experiment(name="test_experiment")
        db_session.add(experiment)
        db_session.commit()

        # Valid status
        model_run = ModelRun(
            experiment_id=experiment.id,
            model_name="test_model",
            status="RUNNING"
        )
        db_session.add(model_run)
        db_session.commit()

        # Invalid status should raise error
        model_run.status = "INVALID_STATUS"
        with pytest.raises(ValueError, match="Status must be one of"):
            db_session.commit()

    def test_feature_store_creation(self, db_session):
        """Test feature store model creation."""
        feature = FeatureStore(
            entity_id="user_123",
            feature_group="demographics",
            feature_name="age",
            feature_value=25,
            data_type="numeric",
            event_timestamp=datetime.utcnow(),
            source_system="user_service",
            tags={"version": "1.0"}
        )

        db_session.add(feature)
        db_session.commit()

        # Verify feature was created
        retrieved = db_session.query(FeatureStore).filter_by(
            entity_id="user_123", feature_name="age"
        ).first()
        assert retrieved is not None
        assert retrieved.feature_value == 25
        assert retrieved.data_type == "numeric"

    def test_feature_store_unique_constraint(self, db_session):
        """Test feature store uniqueness constraint."""
        timestamp = datetime.utcnow()

        # Create first feature
        feature1 = FeatureStore(
            entity_id="user_123",
            feature_group="demographics",
            feature_name="age",
            feature_value=25,
            data_type="numeric",
            event_timestamp=timestamp
        )
        db_session.add(feature1)
        db_session.commit()

        # Try to create duplicate feature (same entity, group, name, timestamp)
        feature2 = FeatureStore(
            entity_id="user_123",
            feature_group="demographics",
            feature_name="age",
            feature_value=30,
            data_type="numeric",
            event_timestamp=timestamp
        )
        db_session.add(feature2)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_feature_store_data_type_validation(self, db_session):
        """Test feature store data type validation."""
        feature = FeatureStore(
            entity_id="user_123",
            feature_group="test",
            feature_name="test_feature",
            feature_value="test",
            data_type="categorical",
            event_timestamp=datetime.utcnow()
        )
        db_session.add(feature)
        db_session.commit()

        # Invalid data type should raise error
        feature.data_type = "invalid_type"
        with pytest.raises(ValueError, match="Data type must be one of"):
            db_session.commit()

    def test_prediction_log_creation(self, db_session):
        """Test prediction log creation."""
        # Create related models first
        experiment = Experiment(name="test_experiment")
        db_session.add(experiment)
        db_session.commit()

        model_run = ModelRun(
            experiment_id=experiment.id,
            model_name="fraud_detector",
            status="FINISHED"
        )
        db_session.add(model_run)
        db_session.commit()

        # Create prediction log
        prediction_log = PredictionLog(
            model_run_id=model_run.id,
            request_id="req_123",
            model_name="fraud_detector",
            model_version="1.0",
            input_features={"amount": 100.0, "merchant": "test"},
            prediction={"fraud_probability": 0.1, "decision": "approved"},
            probabilities=[0.9, 0.1],
            latency_ms=25.5,
            user_id="user_123",
            status_code=200
        )

        db_session.add(prediction_log)
        db_session.commit()

        # Verify prediction log was created
        retrieved = db_session.query(PredictionLog).filter_by(request_id="req_123").first()
        assert retrieved is not None
        assert retrieved.model_name == "fraud_detector"
        assert retrieved.input_features["amount"] == 100.0
        assert retrieved.latency_ms == 25.5

    def test_prediction_log_status_code_validation(self, db_session):
        """Test prediction log status code validation."""
        prediction_log = PredictionLog(
            model_name="test_model",
            model_version="1.0",
            input_features={},
            prediction={},
            status_code=200
        )
        db_session.add(prediction_log)
        db_session.commit()

        # Invalid status code should raise error
        prediction_log.status_code = 999
        with pytest.raises(ValueError, match="Status code must be a valid HTTP status code"):
            db_session.commit()

    def test_data_drift_monitoring_creation(self, db_session):
        """Test data drift monitoring model creation."""
        drift_record = DataDriftMonitoring(
            model_name="fraud_detector",
            model_version="1.0",
            window_start=datetime.utcnow() - timedelta(days=1),
            window_end=datetime.utcnow(),
            drift_score=0.15,
            drift_threshold=0.1,
            is_drift_detected=True,
            feature_drift_scores={"amount": 0.2, "merchant_category": 0.05},
            drifted_features=["amount"],
            psi_score=0.18,
            reference_period_start=datetime.utcnow() - timedelta(days=30),
            reference_period_end=datetime.utcnow() - timedelta(days=7),
            reference_data_size=10000,
            current_data_size=1000,
            detection_method="psi"
        )

        db_session.add(drift_record)
        db_session.commit()

        # Verify drift record was created
        retrieved = db_session.query(DataDriftMonitoring).filter_by(
            model_name="fraud_detector"
        ).first()
        assert retrieved is not None
        assert retrieved.drift_score == 0.15
        assert retrieved.is_drift_detected is True
        assert "amount" in retrieved.drifted_features

    def test_model_relationships(self, db_session):
        """Test model relationships."""
        # Create experiment with model run
        experiment = Experiment(name="test_experiment")
        db_session.add(experiment)
        db_session.commit()

        model_run = ModelRun(
            experiment_id=experiment.id,
            model_name="test_model",
            status="FINISHED"
        )
        db_session.add(model_run)
        db_session.commit()

        # Create prediction log linked to model run
        prediction_log = PredictionLog(
            model_run_id=model_run.id,
            model_name="test_model",
            model_version="1.0",
            input_features={},
            prediction={}
        )
        db_session.add(prediction_log)
        db_session.commit()

        # Test relationships
        retrieved_experiment = db_session.query(Experiment).filter_by(name="test_experiment").first()
        assert len(retrieved_experiment.model_runs) == 1
        assert retrieved_experiment.model_runs[0].model_name == "test_model"

        retrieved_model_run = db_session.query(ModelRun).filter_by(model_name="test_model").first()
        assert retrieved_model_run.experiment.name == "test_experiment"
        assert len(retrieved_model_run.prediction_logs) == 1


class TestDatabaseSession:
    """Test database session management."""

    def test_database_manager_initialization(self, test_config):
        """Test database manager initialization."""
        db_manager = DatabaseManager(test_config.database)
        db_manager.initialize()

        assert db_manager.engine is not None
        assert db_manager.session_factory is not None

        db_manager.close()

    def test_session_context_manager(self, test_database):
        """Test session context manager."""
        with test_database.get_session() as session:
            # Create a test record
            experiment = Experiment(name="context_test")
            session.add(experiment)
            # Commit happens automatically on context exit

        # Verify record was saved
        with test_database.get_session() as session:
            retrieved = session.query(Experiment).filter_by(name="context_test").first()
            assert retrieved is not None

    def test_session_rollback_on_error(self, test_database):
        """Test session rollback on error."""
        try:
            with test_database.get_session() as session:
                # Create valid experiment
                experiment = Experiment(name="rollback_test")
                session.add(experiment)
                session.flush()  # Ensure it's added to session

                # Create duplicate to cause error
                duplicate = Experiment(name="rollback_test")
                session.add(duplicate)
                # This should cause rollback
        except IntegrityError:
            pass  # Expected error

        # Verify rollback occurred - no experiment should exist
        with test_database.get_session() as session:
            count = session.query(Experiment).filter_by(name="rollback_test").count()
            assert count == 0

    def test_connection_check(self, test_database):
        """Test database connection checking."""
        assert test_database.check_connection() is True

    def test_connection_info(self, test_database):
        """Test connection pool information."""
        info = test_database.get_connection_info()
        assert isinstance(info, dict)
        # For SQLite, some pool stats might not be available

    def test_create_test_database(self):
        """Test test database creation utility."""
        test_db = create_test_database()

        assert test_db.engine is not None
        assert test_db.check_connection() is True

        # Verify tables were created
        from src.database.models import Base
        metadata = Base.metadata
        table_names = [table.name for table in metadata.sorted_tables]

        expected_tables = [
            "experiments", "model_runs", "feature_store",
            "prediction_logs", "data_drift_monitoring"
        ]

        for table_name in expected_tables:
            assert table_name in table_names

        test_db.close()

    def test_table_creation_and_drop(self, test_config):
        """Test table creation and dropping."""
        db_manager = DatabaseManager(test_config.database)
        db_manager.initialize()

        # Create tables
        db_manager.create_tables()

        # Drop tables
        db_manager.drop_tables()

        db_manager.close()


class TestDatabaseIndexes:
    """Test database indexing and performance."""

    def test_experiment_indexes(self, db_session):
        """Test experiment table indexes work correctly."""
        # Create multiple experiments
        for i in range(10):
            experiment = Experiment(
                name=f"experiment_{i}",
                created_at=datetime.utcnow() - timedelta(days=i)
            )
            db_session.add(experiment)
        db_session.commit()

        # Test name index
        result = db_session.query(Experiment).filter_by(name="experiment_5").first()
        assert result is not None

        # Test created_at index (query by date range)
        cutoff_date = datetime.utcnow() - timedelta(days=5)
        recent_experiments = db_session.query(Experiment).filter(
            Experiment.created_at >= cutoff_date
        ).all()
        assert len(recent_experiments) == 6  # experiments 0-5

    def test_model_run_indexes(self, db_session):
        """Test model run table indexes."""
        # Create experiment
        experiment = Experiment(name="test_experiment")
        db_session.add(experiment)
        db_session.commit()

        # Create multiple model runs
        for i in range(5):
            model_run = ModelRun(
                experiment_id=experiment.id,
                model_name=f"model_{i % 2}",  # Two different model names
                model_version=f"v{i}",
                status="FINISHED",
                start_time=datetime.utcnow() - timedelta(hours=i)
            )
            db_session.add(model_run)
        db_session.commit()

        # Test model_name index
        model_0_runs = db_session.query(ModelRun).filter_by(model_name="model_0").all()
        assert len(model_0_runs) == 3  # Runs 0, 2, 4

        # Test composite index (model_name, model_version)
        specific_run = db_session.query(ModelRun).filter_by(
            model_name="model_1", model_version="v1"
        ).first()
        assert specific_run is not None

    def test_feature_store_indexes(self, db_session):
        """Test feature store table indexes."""
        # Create multiple features
        entities = ["user_1", "user_2", "user_3"]
        feature_groups = ["demographics", "behavior"]
        feature_names = ["age", "income", "clicks"]

        for entity in entities:
            for group in feature_groups:
                for name in feature_names:
                    feature = FeatureStore(
                        entity_id=entity,
                        feature_group=group,
                        feature_name=name,
                        feature_value=42,
                        data_type="numeric",
                        event_timestamp=datetime.utcnow()
                    )
                    db_session.add(feature)
        db_session.commit()

        # Test entity_id index
        user_1_features = db_session.query(FeatureStore).filter_by(entity_id="user_1").all()
        assert len(user_1_features) == 6  # 2 groups * 3 features

        # Test composite index (entity_id, feature_group, feature_name)
        specific_feature = db_session.query(FeatureStore).filter_by(
            entity_id="user_2",
            feature_group="demographics",
            feature_name="age"
        ).first()
        assert specific_feature is not None