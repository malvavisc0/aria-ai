"""
Tests for file operation decorators.

This module tests the decorators used in file operations, focusing on
error handling and input validation edge cases.
"""

from aria.tools.files.decorators import (
    with_file_operation_error_handling,
    with_input_validation,
)
from aria.tools.files.exceptions import FileSecurityError


class TestWithFileOperationErrorHandling:
    """Test suite for with_file_operation_error_handling decorator."""

    def test_decorator_handles_oserror(self):
        """Test that decorator converts OSError to an error response."""

        @with_file_operation_error_handling("test_operation")
        def function_that_raises_oserror(reason: str, file_name: str):
            raise OSError("Permission denied")

        result = function_that_raises_oserror("test", "test.txt")
        assert isinstance(result, str)
        assert "Permission" in result or "denied" in result.lower()

    def test_decorator_handles_generic_exception(self):
        """Test decorator converts generic Exception to error response."""

        @with_file_operation_error_handling("test_operation")
        def function_that_raises_generic_exception(reason: str, file_name: str):
            raise ValueError("Unexpected error")

        result = function_that_raises_generic_exception("test", "test.txt")
        assert isinstance(result, str)
        assert "Unexpected error" in result

    def test_decorator_handles_file_security_error(self):
        """Test decorator converts FileSecurityError to error response."""

        @with_file_operation_error_handling("test_operation")
        def function_that_raises_security_error(reason: str, file_name: str):
            raise FileSecurityError("Security violation")

        result = function_that_raises_security_error("test", "test.txt")
        assert isinstance(result, str)
        assert "Security" in result


class TestWithInputValidation:
    """Test suite for with_input_validation decorator."""

    def test_decorator_validates_file_name(self):
        """Test that decorator validates file_name parameter."""

        @with_input_validation()
        def function_with_file_name(file_name):
            return f"Processing: {file_name}"

        # Valid file name should work
        result = function_with_file_name("test.txt")
        assert result == "Processing: test.txt"

    def test_decorator_with_validation_params(self):
        """Test decorator with specific validation parameters."""

        @with_input_validation(contents=True)
        def function_with_contents(file_name, contents):
            return f"Writing {len(contents)} bytes to {file_name}"

        result = function_with_contents("test.txt", "Hello World")
        assert "Writing 11 bytes" in result

    def test_decorator_skips_none_values(self):
        """Test that decorator skips validation for None values."""

        @with_input_validation(contents=True, offset=True)
        def function_with_optional_params(file_name, contents=None, offset=None):
            return f"File: {file_name}"

        # Should not raise error even though contents and offset are None
        result = function_with_optional_params("test.txt")
        assert result == "File: test.txt"

    def test_decorator_converts_security_error_to_operation_error(self):
        """Test decorator converts FileSecurityError to error response."""
        from unittest.mock import patch

        @with_input_validation()
        def function_to_test(file_name):
            return "Success"

        # Mock _validate_inputs to raise FileSecurityError
        with patch(
            "aria.tools.files.decorators._validate_inputs",
            side_effect=FileSecurityError("Invalid path"),
        ):
            result = function_to_test("../invalid.txt")
            assert isinstance(result, str)
            assert "Invalid path" in result

    def test_decorator_with_multiple_validation_params(self):
        """Test decorator with multiple validation parameters."""

        @with_input_validation(contents=True, chunk_size=True, offset=True)
        def complex_function(file_name, contents, chunk_size, offset):
            return f"File: {file_name}, Size: {chunk_size}, Offset: {offset}"

        result = complex_function("test.txt", "data", 100, 0)
        assert "File: test.txt" in result
        assert "Size: 100" in result
        assert "Offset: 0" in result


