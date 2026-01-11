"""Base template for all test scripts."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Optional, TypeVar

from .test_config import TestConfig

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


@dataclass
class TestResult(Generic[TOutput]):
    """Standardized test result."""

    success: bool
    output: Optional[TOutput] = None
    error: Optional[str] = None
    assertions_passed: int = 0
    assertions_failed: int = 0
    warnings: list[str] = field(default_factory=list)


class BaseTest(ABC, Generic[TInput, TOutput]):
    """
    Base class for all test scripts.

    Provides:
    - Fixture loading/saving
    - Assertion utilities
    - Standard output formatting
    - Live vs fixture mode handling

    Type Parameters:
        TInput: The input type for the test
        TOutput: The output type from the component under test
    """

    def __init__(
        self,
        *,
        fixture_dir: Path,
        output_dir: Path,
        use_live_mode: bool = False,
    ):
        """
        Initialize the test.

        Args:
            fixture_dir: Directory containing test fixtures
            output_dir: Directory to write test outputs
            use_live_mode: If True, make live API calls; if False, use fixtures
        """
        self.fixture_dir = fixture_dir
        self.output_dir = output_dir
        self.use_live_mode = use_live_mode
        self.config = TestConfig()

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def load_input(self) -> TInput:
        """
        Load test input (from fixture or sample data).

        Returns:
            Input data for the component under test
        """
        pass

    @abstractmethod
    def run_component(self, input_data: TInput) -> TOutput:
        """
        Run the component under test.

        Args:
            input_data: Input data loaded from load_input()

        Returns:
            Output from the component
        """
        pass

    @abstractmethod
    def validate_output(self, output: TOutput) -> TestResult[TOutput]:
        """
        Validate the output against expected results.

        Args:
            output: Output from run_component()

        Returns:
            TestResult with validation status and details
        """
        pass

    def load_fixture(self, filename: str) -> Any:
        """
        Load a JSON fixture file.

        Args:
            filename: Name of the fixture file (relative to fixture_dir)

        Returns:
            Parsed JSON data

        Raises:
            FileNotFoundError: If fixture file doesn't exist
        """
        fixture_path = self.fixture_dir / filename
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_path}")

        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_output(self, output: Any, filename: str) -> Path:
        """
        Save output to file for inspection.

        Args:
            output: Output data to save
            filename: Name of the output file

        Returns:
            Path to the saved output file
        """
        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            if hasattr(output, "to_dict"):
                json.dump(output.to_dict(), f, indent=2, default=str)
            elif isinstance(output, list) and output and hasattr(output[0], "to_dict"):
                json.dump([item.to_dict() for item in output], f, indent=2, default=str)
            else:
                json.dump(output, f, indent=2, default=str)
        return output_path

    def assert_equals(self, actual: Any, expected: Any, msg: str = "") -> bool:
        """
        Assert equality with detailed error messages.

        Args:
            actual: Actual value
            expected: Expected value
            msg: Custom assertion message

        Returns:
            True if equal, False otherwise
        """
        if actual == expected:
            print(f"  ✓ {msg or 'Assertion passed'}")
            return True

        error_msg = f"Assertion failed: {msg}" if msg else "Assertion failed"
        print(f"  ✗ {error_msg}")
        print(f"    Expected: {expected}")
        print(f"    Actual:   {actual}")
        return False

    def assert_contains(self, container: Any, item: Any, msg: str = "") -> bool:
        """
        Assert item is in container.

        Args:
            container: Container to check
            item: Item to find
            msg: Custom assertion message

        Returns:
            True if item in container, False otherwise
        """
        if item in container:
            print(f"  ✓ {msg or 'Assertion passed'}")
            return True

        error_msg = f"Assertion failed: {msg}" if msg else "Assertion failed"
        print(f"  ✗ {error_msg}")
        print(f"    Item not found: {item}")
        print(f"    Container has {len(container) if hasattr(container, '__len__') else '?'} items")
        return False

    def assert_not_empty(self, value: Any, msg: str = "") -> bool:
        """
        Assert value is not empty.

        Args:
            value: Value to check
            msg: Custom assertion message

        Returns:
            True if not empty, False otherwise
        """
        is_not_empty = bool(value)
        if is_not_empty:
            print(f"  ✓ {msg or 'Assertion passed'}")
            return True

        error_msg = f"Assertion failed: {msg}" if msg else "Assertion failed"
        print(f"  ✗ {error_msg}")
        print(f"    Value is empty: {value}")
        return False

    def run(self) -> TestResult[TOutput]:
        """
        Execute the test.

        Returns:
            TestResult with test execution status and details
        """
        print("=" * 80)
        print(f"Running Test: {self.__class__.__name__}")
        print("=" * 80)
        print(f"Mode: {'LIVE' if self.use_live_mode else 'FIXTURE'}")
        print(f"Fixture dir: {self.fixture_dir}")
        print(f"Output dir: {self.output_dir}")
        print()

        try:
            # Load input
            print("[1] Loading input...")
            input_data = self.load_input()
            print("  ✓ Input loaded")

            # Run component
            print("\n[2] Running component...")
            output = self.run_component(input_data)
            print("  ✓ Component executed")

            # Save output
            print("\n[3] Saving output...")
            output_file = self.save_output(output, "output.json")
            print(f"  ✓ Output saved to: {output_file}")

            # Validate
            print("\n[4] Validating output...")
            result = self.validate_output(output)

            # Print summary
            print("\n" + "=" * 80)
            if result.success:
                print(f"✓ Test PASSED")
                print(f"  Assertions passed: {result.assertions_passed}")
            else:
                print(f"✗ Test FAILED")
                print(f"  Assertions passed: {result.assertions_passed}")
                print(f"  Assertions failed: {result.assertions_failed}")
                if result.error:
                    print(f"  Error: {result.error}")

            if result.warnings:
                print("\nWarnings:")
                for warning in result.warnings:
                    print(f"  ⚠ {warning}")

            print("=" * 80)

            return result

        except Exception as e:
            import traceback

            error_msg = f"Test execution failed: {e}"
            print(f"\n✗ {error_msg}")
            print("\nStack trace:")
            traceback.print_exc()
            print("\n" + "=" * 80)

            return TestResult(success=False, error=error_msg)
