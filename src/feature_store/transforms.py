"""Feature transformation utilities for data preprocessing and validation."""

from abc import ABC, abstractmethod
from datetime import datetime
from datetime import timezone as tz
from typing import Any, List, Optional, Union

import structlog

logger = structlog.get_logger()


class FeatureTransform(ABC):
    """Abstract base class for feature transformations."""

    def __init__(self, fill_missing: bool = True, default_value: Any = None):
        """Initialize feature transform.

        Args:
            fill_missing: Whether to fill missing values
            default_value: Default value for missing features
        """
        self.fill_missing = fill_missing
        self.default_value = default_value
        self.logger = logger.bind(component=self.__class__.__name__)

    @abstractmethod
    def transform(self, value: Any) -> Any:
        """Transform a feature value.

        Args:
            value: Input feature value

        Returns:
            Transformed feature value
        """
        pass

    def _handle_missing(self, value: Any) -> Any:
        """Handle missing values.

        Args:
            value: Input value

        Returns:
            Value or default if missing
        """
        if value is None or (isinstance(value, str) and value.strip() == ""):
            if self.fill_missing:
                return self.default_value
            else:
                return None
        return value


class NumericTransform(FeatureTransform):
    """Transformation for numeric features with bounds checking and normalization."""

    def __init__(
        self,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        normalize: bool = False,
        clip_outliers: bool = True,
        fill_missing: bool = True,
        default_value: float = 0.0,
    ):
        """Initialize numeric transform.

        Args:
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            normalize: Whether to normalize to [0, 1] range
            clip_outliers: Whether to clip values to min/max bounds
            fill_missing: Whether to fill missing values
            default_value: Default value for missing features
        """
        super().__init__(fill_missing=fill_missing, default_value=default_value)
        self.min_value = min_value
        self.max_value = max_value
        self.normalize = normalize
        self.clip_outliers = clip_outliers

    def transform(self, value: Any) -> float:
        """Transform numeric value with bounds checking and normalization.

        Args:
            value: Input numeric value

        Returns:
            Transformed numeric value
        """
        # Handle missing values
        value = self._handle_missing(value)
        if value is None:
            return None

        try:
            # Convert to float
            numeric_value = float(value)

            # Apply bounds checking
            if self.clip_outliers:
                if self.min_value is not None:
                    numeric_value = max(numeric_value, self.min_value)
                if self.max_value is not None:
                    numeric_value = min(numeric_value, self.max_value)

            # Apply normalization
            if (
                self.normalize
                and self.min_value is not None
                and self.max_value is not None
            ):
                if self.max_value > self.min_value:
                    numeric_value = (numeric_value - self.min_value) / (
                        self.max_value - self.min_value
                    )

            return numeric_value

        except (ValueError, TypeError) as e:
            self.logger.warning(
                "Failed to transform numeric value", value=value, error=str(e)
            )
            return self.default_value if self.fill_missing else None


class CategoricalTransform(FeatureTransform):
    """Transformation for categorical features with validation and encoding."""

    def __init__(
        self,
        valid_categories: Optional[List[str]] = None,
        case_sensitive: bool = False,
        encode_as_numeric: bool = False,
        fill_missing: bool = True,
        default_value: str = "unknown",
    ):
        """Initialize categorical transform.

        Args:
            valid_categories: List of valid category values
            case_sensitive: Whether category matching is case sensitive
            encode_as_numeric: Whether to encode categories as numeric values
            fill_missing: Whether to fill missing values
            default_value: Default value for missing/invalid categories
        """
        super().__init__(fill_missing=fill_missing, default_value=default_value)
        self.valid_categories = valid_categories or []
        self.case_sensitive = case_sensitive
        self.encode_as_numeric = encode_as_numeric

        # Create category mapping for numeric encoding
        if self.encode_as_numeric and self.valid_categories:
            self.category_map = {
                cat: idx for idx, cat in enumerate(self.valid_categories)
            }
            if self.default_value not in self.category_map:
                self.category_map[self.default_value] = len(self.valid_categories)

    def transform(self, value: Any) -> Union[str, int]:
        """Transform categorical value with validation and encoding.

        Args:
            value: Input categorical value

        Returns:
            Transformed categorical value (string or numeric)
        """
        # Handle missing values
        value = self._handle_missing(value)
        if value is None:
            return None

        try:
            # Convert to string
            str_value = str(value).strip()

            # Handle case sensitivity
            if not self.case_sensitive:
                str_value = str_value.lower()
                valid_categories_lower = [cat.lower() for cat in self.valid_categories]
            else:
                valid_categories_lower = self.valid_categories

            # Validate against allowed categories
            if self.valid_categories:
                if str_value not in valid_categories_lower:
                    if self.fill_missing:
                        str_value = self.default_value
                    else:
                        return None

            # Apply numeric encoding if requested
            if self.encode_as_numeric:
                return self.category_map.get(
                    str_value, self.category_map.get(self.default_value, 0)
                )

            return str_value

        except Exception as e:
            self.logger.warning(
                "Failed to transform categorical value", value=value, error=str(e)
            )
            if self.encode_as_numeric:
                return (
                    self.category_map.get(self.default_value, 0)
                    if self.fill_missing
                    else None
                )
            else:
                return self.default_value if self.fill_missing else None


class DateTimeTransform(FeatureTransform):
    """Transformation for datetime features with extraction and formatting."""

    def __init__(
        self,
        extract_components: bool = True,
        output_format: str = "timestamp",
        timezone: Optional[str] = None,
        fill_missing: bool = True,
        default_value: Optional[datetime] = None,
    ):
        """Initialize datetime transform.

        Args:
            extract_components: Whether to extract datetime components
            output_format: Output format ('timestamp', 'iso', 'components')
            timezone: Target timezone for conversion
            fill_missing: Whether to fill missing values
            default_value: Default datetime for missing values
        """
        if default_value is None:
            default_value = datetime.now(tz.utc)

        super().__init__(fill_missing=fill_missing, default_value=default_value)
        self.extract_components = extract_components
        self.output_format = output_format
        self.timezone = timezone

    def transform(self, value: Any) -> Union[float, str, dict]:
        """Transform datetime value with extraction and formatting.

        Args:
            value: Input datetime value

        Returns:
            Transformed datetime value (timestamp, ISO string, or components dict)
        """
        # Handle missing values
        value = self._handle_missing(value)
        if value is None:
            return None

        try:
            # Parse datetime
            if isinstance(value, datetime):
                dt_value = value
            elif isinstance(value, str):
                # Try common datetime formats
                formats = [
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d",
                    "%m/%d/%Y",
                    "%d/%m/%Y",
                ]
                dt_value = None
                for fmt in formats:
                    try:
                        dt_value = datetime.strptime(value, fmt)
                        break
                    except ValueError:
                        continue

                if dt_value is None:
                    raise ValueError(f"Unable to parse datetime: {value}")
            else:
                # Assume timestamp
                dt_value = datetime.fromtimestamp(float(value))

            # Apply output formatting
            if self.output_format == "timestamp":
                return dt_value.timestamp()
            elif self.output_format == "iso":
                return dt_value.isoformat()
            elif self.output_format == "components":
                return {
                    "year": dt_value.year,
                    "month": dt_value.month,
                    "day": dt_value.day,
                    "hour": dt_value.hour,
                    "minute": dt_value.minute,
                    "second": dt_value.second,
                    "weekday": dt_value.weekday(),
                    "day_of_year": dt_value.timetuple().tm_yday,
                }
            else:
                return dt_value.timestamp()

        except Exception as e:
            self.logger.warning(
                "Failed to transform datetime value", value=value, error=str(e)
            )
            if self.fill_missing:
                return self.transform(self.default_value)
            else:
                return None


class BooleanTransform(FeatureTransform):
    """Transformation for boolean features with flexible input handling."""

    def __init__(
        self,
        true_values: Optional[List[str]] = None,
        false_values: Optional[List[str]] = None,
        output_as_numeric: bool = False,
        fill_missing: bool = True,
        default_value: bool = False,
    ):
        """Initialize boolean transform.

        Args:
            true_values: List of string values that should be treated as True
            false_values: List of string values that should be treated as False
            output_as_numeric: Whether to output 1/0 instead of True/False
            fill_missing: Whether to fill missing values
            default_value: Default boolean value for missing features
        """
        super().__init__(fill_missing=fill_missing, default_value=default_value)

        self.true_values = true_values or ["true", "yes", "1", "y", "on", "enabled"]
        self.false_values = false_values or ["false", "no", "0", "n", "off", "disabled"]
        self.output_as_numeric = output_as_numeric

    def transform(self, value: Any) -> Union[bool, int]:
        """Transform boolean value with flexible input handling.

        Args:
            value: Input boolean value

        Returns:
            Transformed boolean value (bool or int)
        """
        # Handle missing values
        value = self._handle_missing(value)
        if value is None:
            return None

        try:
            # Handle different input types
            if isinstance(value, bool):
                bool_value = value
            elif isinstance(value, (int, float)):
                bool_value = bool(value)
            elif isinstance(value, str):
                str_value = value.strip().lower()
                if str_value in self.true_values:
                    bool_value = True
                elif str_value in self.false_values:
                    bool_value = False
                else:
                    # Default interpretation
                    bool_value = bool(value) if value else False
            else:
                bool_value = bool(value)

            # Apply output formatting
            if self.output_as_numeric:
                return 1 if bool_value else 0
            else:
                return bool_value

        except Exception as e:
            self.logger.warning(
                "Failed to transform boolean value", value=value, error=str(e)
            )
            default_output = self.default_value if self.fill_missing else None
            if default_output is not None and self.output_as_numeric:
                return 1 if default_output else 0
            return default_output


class TextTransform(FeatureTransform):
    """Transformation for text features with cleaning and normalization."""

    def __init__(
        self,
        max_length: Optional[int] = None,
        lowercase: bool = True,
        strip_whitespace: bool = True,
        remove_special_chars: bool = False,
        fill_missing: bool = True,
        default_value: str = "",
    ):
        """Initialize text transform.

        Args:
            max_length: Maximum text length (truncate if longer)
            lowercase: Whether to convert to lowercase
            strip_whitespace: Whether to strip leading/trailing whitespace
            remove_special_chars: Whether to remove special characters
            fill_missing: Whether to fill missing values
            default_value: Default text value for missing features
        """
        super().__init__(fill_missing=fill_missing, default_value=default_value)
        self.max_length = max_length
        self.lowercase = lowercase
        self.strip_whitespace = strip_whitespace
        self.remove_special_chars = remove_special_chars

    def transform(self, value: Any) -> str:
        """Transform text value with cleaning and normalization.

        Args:
            value: Input text value

        Returns:
            Transformed text value
        """
        # Handle missing values
        value = self._handle_missing(value)
        if value is None:
            return None

        try:
            # Convert to string
            text_value = str(value)

            # Apply transformations
            if self.strip_whitespace:
                text_value = text_value.strip()

            if self.lowercase:
                text_value = text_value.lower()

            if self.remove_special_chars:
                import re

                text_value = re.sub(r"[^a-zA-Z0-9\s]", "", text_value)

            if self.max_length is not None:
                text_value = text_value[: self.max_length]

            return text_value

        except Exception as e:
            self.logger.warning(
                "Failed to transform text value", value=value, error=str(e)
            )
            return self.default_value if self.fill_missing else None
