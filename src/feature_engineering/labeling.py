"""Labeling strategies for training data assembly.

Assigns labels to Beam-produced features post-pipeline.
Production-realistic: labels never arrive with raw events.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import pandas as pd


class LabelingStrategy(ABC):
    """Abstract base for label assignment strategies."""

    @abstractmethod
    def assign_labels(self, df: pd.DataFrame) -> pd.Series:
        """Assign labels to a DataFrame of features.

        Args:
            df: DataFrame with Beam-produced feature columns.

        Returns:
            Series of integer labels (0 or 1).
        """


class RuleBasedLabeling(LabelingStrategy):
    """Fraud heuristic matching generate_data.py logic applied to Beam features.

    Risk factors (accumulated, capped at 1.0):
        - Merchant base fraud rate (category-dependent)
        - Late night / early morning (hour < 6 or hour >= 22): +0.2
        - High amount (> 1000): +0.3
        - High-risk category (jewelry, cash_advance): +0.4
        - Weekend cash advance: +0.3

    A record is labeled fraud (1) when the accumulated risk exceeds a
    configurable threshold (default 0.5).  The threshold is tuned to
    produce ~5 % fraud rate on realistic transaction distributions.
    """

    MERCHANT_BASE_RATES: Dict[str, float] = {
        "grocery": 0.01,
        "gas_station": 0.02,
        "restaurant": 0.03,
        "pharmacy": 0.01,
        "clothing": 0.04,
        "online_retail": 0.06,
        "electronics": 0.08,
        "travel": 0.10,
        "jewelry": 0.15,
        "cash_advance": 0.25,
    }

    HIGH_RISK_CATEGORIES = {"jewelry", "cash_advance"}

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    def assign_labels(self, df: pd.DataFrame) -> pd.Series:
        """Assign fraud labels based on accumulated risk factors.

        When a pre-computed ``risk_score`` column is present (e.g. from the
        Kinesis producer which already combines user risk profile with
        transaction-level factors), it is used directly.  The heuristic
        accumulation is only applied when ``risk_score`` is absent.
        """
        # If the data already carries a composite risk_score (produced by the
        # event generator), use it directly to avoid double-counting.
        if "risk_score" in df.columns:
            risk = df["risk_score"].astype(float).clip(upper=1.0)
            return (risk >= self.threshold).astype(int)

        # Fallback: accumulate risk from individual heuristic factors.
        risk = pd.Series(0.0, index=df.index)

        # Merchant base rate
        if "merchant_category" in df.columns:
            risk += df["merchant_category"].map(self.MERCHANT_BASE_RATES).fillna(0.03)

        # Night transactions
        if "hour_of_day" in df.columns:
            is_night = (df["hour_of_day"] < 6) | (df["hour_of_day"] >= 22)
            risk += is_night.astype(float) * 0.2

        # High amount
        if "amount" in df.columns:
            risk += (df["amount"] > 1000).astype(float) * 0.3

        # High-risk merchant category
        if "merchant_category" in df.columns:
            is_high_risk = df["merchant_category"].isin(self.HIGH_RISK_CATEGORIES)
            risk += is_high_risk.astype(float) * 0.4

        # Weekend cash advance interaction
        if "is_weekend" in df.columns and "merchant_category" in df.columns:
            weekend_cash = df["is_weekend"].astype(bool) & (
                df["merchant_category"] == "cash_advance"
            )
            risk += weekend_cash.astype(float) * 0.3

        risk = risk.clip(upper=1.0)
        return (risk >= self.threshold).astype(int)


class FileBasedLabeling(LabelingStrategy):
    """Join labels from an external ground-truth CSV by event ID.

    Useful when human-reviewed labels are available post-hoc.
    """

    def __init__(
        self,
        labels_path: str,
        id_column: str = "message_id",
        label_column: str = "label",
    ) -> None:
        self.labels_path = labels_path
        self.id_column = id_column
        self.label_column = label_column
        self._labels_df: Optional[pd.DataFrame] = None

    def _load_labels(self) -> pd.DataFrame:
        if self._labels_df is None:
            self._labels_df = pd.read_csv(
                self.labels_path, usecols=[self.id_column, self.label_column]
            )
        return self._labels_df

    def assign_labels(self, df: pd.DataFrame) -> pd.Series:
        """Join labels from external file by event ID."""
        labels_df = self._load_labels()

        if self.id_column not in df.columns:
            raise ValueError(
                f"DataFrame missing join column '{self.id_column}'. "
                f"Available: {list(df.columns)}"
            )

        merged = df[[self.id_column]].merge(labels_df, on=self.id_column, how="left")
        return merged[self.label_column].fillna(0).astype(int)


LABELING_STRATEGIES: Dict[str, type] = {
    "rule_based": RuleBasedLabeling,
    "file_based": FileBasedLabeling,
}


def get_labeling_strategy(name: str, **kwargs: Any) -> LabelingStrategy:
    """Factory for labeling strategies.

    Args:
        name: Strategy name ("rule_based" or "file_based").
        **kwargs: Strategy-specific arguments.

    Returns:
        Configured LabelingStrategy instance.
    """
    cls = LABELING_STRATEGIES.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown labeling strategy '{name}'. "
            f"Available: {list(LABELING_STRATEGIES.keys())}"
        )
    return cls(**kwargs)
