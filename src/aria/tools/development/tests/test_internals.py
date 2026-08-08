"""
Comprehensive tests for development/_internals.py module.

This test suite covers edge cases, error handling, and security features
in the internal helper functions for Python code execution.
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from aria.tools import safe_json, utc_timestamp
from aria.tools.constants import MAX_TIMEOUT
from aria.tools.development._internals import (
    _build_response,
    _capture_execution_output,
    _create_safe_globals,
    _error_response,
    _execute_without_capture,
    _read_file_safely,
    _time_limit,
    _validate_inputs,
    _validate_timeout,
)
from aria.tools.development.exceptions import (
    PythonExecutionError,
    PythonExecutionTimeoutError,
    PythonRunnerError,
    PythonSecurityError,
    PythonSyntaxValidationError,
)


class TestTimestamp:
    """Test timestamp generation"""

    def test_timestamp_format(self):
        """Test that timestamp is in ISO format"""
        ts = utc_timestamp()
        assert isinstance(ts, str)
        assert "T" in ts  # ISO format contains T separator
        # Should be parseable as datetime
        from datetime import datetime

        datetime.fromisoformat(ts)


class TestSafeJson:
    """Test safe JSON serialization"""

    def test_safe_json_success(self):
        """Test successful JSON serialization"""
        data = {"key": "value", "number": 42}
        result = safe_json(data)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == data

    def test_safe_json_with_unicode(self):
        """Test JSON serialization with unicode characters"""
        data = {"message": "Hello 世界 🌍"}
        result = safe_json(data)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == data

    def test_safe_json_serialization_error(self):
        """Test JSON serialization with non-serializable object"""

        # Create a non-serializable object
        class NonSerializable:
            pass

        data = {"obj": NonSerializable()}
        result = safe_json(data)
        assert isinstance(result, str)
        parsed = json.loads(result)
        # safe_json uses a default handler that converts non-serializable
        # objects to strings rather than raising an error
        assert "obj" in parsed
        assert "NonSerializable" in parsed["obj"]


class TestBuildResponse:
    """Test response building"""

    def test_build_response_success(self):
        """Test building successful response"""
        result = _build_response("test_op", result={"data": "value"})
        parsed = json.loads(result)
        assert parsed["data"]["tool"] == "test_op"
        assert parsed["data"]["result"]["data"] == "value"
        assert "timestamp" in parsed["context"]

    def test_build_response_with_error(self):
        """Test building error response"""
        result = _build_response("test_op", error="Something went wrong")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["data"]["error"] == "Something went wrong"
        assert parsed["context"]["error"] == "Something went wrong"

    def test_build_response_with_metadata(self):
        """Test building response with additional metadata"""
        result = _build_response(
            "test_op", result={"data": "value"}, custom_field="custom_value"
        )
        parsed = json.loads(result)
        assert parsed["context"]["custom_field"] == "custom_value"


class TestErrorResponse:
    """Test error response generation"""

    def test_error_response_security_error(self):
        """Test error response for PythonSecurityError"""
        exc = PythonSecurityError("Security violation detected")
        result = _error_response("test_op", "test_code", exc, "testing reason")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "PythonSecurityError"
        assert "Security violation" in parsed["error"]["message"]
        assert parsed["error"]["recoverable"] is False
        assert "how_to_fix" in parsed["error"]

    def test_error_response_syntax_error(self):
        """Test error response for PythonSyntaxValidationError"""
        exc = PythonSyntaxValidationError("Invalid syntax")
        result = _error_response("test_op", "test_code", exc, "testing reason")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        error_type = parsed["error"]["type"]
        assert error_type == "PythonSyntaxValidationError"
        # The message now contains the original exception message
        assert "Invalid syntax" in parsed["error"]["message"]
        assert parsed["error"]["recoverable"] is True

    def test_error_response_timeout_error(self):
        """Test error response for PythonExecutionTimeoutError"""
        exc = PythonExecutionTimeoutError("Execution timed out")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "PythonExecutionTimeoutError"
        # The message now contains the original exception message
        assert "Execution timed out" in parsed["error"]["message"]

    def test_error_response_execution_error(self):
        """Test error response for PythonExecutionError"""
        exc = PythonExecutionError("Execution failed")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "PythonExecutionError"
        assert "Execution failed" in parsed["error"]["message"]

    def test_error_response_runner_error(self):
        """Test error response for PythonRunnerError"""
        exc = PythonRunnerError("Runner error")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "PythonRunnerError"
        assert "Runner error" in parsed["error"]["message"]

    def test_error_response_file_not_found(self):
        """Test error response for FileNotFoundError"""
        exc = FileNotFoundError("File not found")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "FileNotFoundError"
        # The message now contains the original exception message
        assert "File not found" in parsed["error"]["message"]

    def test_error_response_permission_error(self):
        """Test error response for PermissionError"""
        exc = PermissionError("Permission denied")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "PermissionError"
        # The message now contains the original exception message
        assert "Permission denied" in parsed["error"]["message"]

    def test_error_response_os_error(self):
        """Test error response for OSError"""
        exc = OSError("OS error occurred")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "OSError"
        assert "OS error" in parsed["error"]["message"]

    def test_error_response_value_error(self):
        """Test error response for ValueError"""
        exc = ValueError("Invalid value")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "ValueError"
        assert "Invalid value" in parsed["error"]["message"]

    def test_error_response_unexpected_error(self):
        """Test error response for unexpected exception"""
        exc = RuntimeError("Unexpected error")
        result = _error_response("test_op", "test_code", exc)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error"]["type"] == "RuntimeError"
        assert "Unexpected error" in parsed["error"]["message"]


class TestValidateInputs:
    """Test input validation"""

    def test_validate_inputs_valid_code(self):
        """Test validation with valid code"""
        _validate_inputs(code="print('hello')")
        # Should not raise

    def test_validate_inputs_non_string_code(self):
        """Test validation with non-string code"""
        with pytest.raises(PythonSecurityError, match="Code must be a string"):
            _validate_inputs(code=123)  # type: ignore[arg-type]

    def test_validate_inputs_large_code(self):
        """Test validation with extremely large code"""
        large_code = "x = 1\n" * 10_000_001  # Exceeds 10MB limit
        with pytest.raises(
            PythonSecurityError, match="Code size exceeds maximum limit"
        ):
            _validate_inputs(code=large_code)

    def test_validate_inputs_non_integer_timeout(self):
        """Test validation with non-integer timeout"""
        with pytest.raises(ValueError, match="Timeout must be an integer"):
            _validate_inputs(timeout="10")  # type: ignore[arg-type]

    def test_validate_inputs_negative_timeout(self):
        """Test validation with negative timeout"""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            _validate_inputs(timeout=-1)

    def test_validate_inputs_zero_timeout(self):
        """Test validation with zero timeout"""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            _validate_inputs(timeout=0)

    def test_validate_inputs_timeout_exceeds_max(self):
        """Test validation with timeout exceeding maximum"""
        with pytest.raises(ValueError, match="exceeds maximum limit"):
            _validate_inputs(timeout=MAX_TIMEOUT + 1)

    def test_validate_inputs_non_string_filename(self):
        """Test validation with non-string filename"""
        with pytest.raises(PythonSecurityError, match="Filename must be a string"):
            _validate_inputs(filename=123)  # type: ignore[arg-type]

    def test_validate_inputs_path_traversal_filename(self):
        """Test validation with path traversal in filename"""
        with pytest.raises(
            PythonSecurityError, match="Path traversal attempt detected"
        ):
            _validate_inputs(filename="../etc/passwd")

    def test_validate_inputs_non_string_file_path(self):
        """Test validation with non-string file_path"""
        with pytest.raises(PythonSecurityError, match="File path must be a string"):
            _validate_inputs(file_path=123)  # type: ignore[arg-type]

    def test_validate_inputs_empty_file_path(self):
        """Test validation with empty file_path"""
        with pytest.raises(PythonSecurityError, match="File path cannot be empty"):
            _validate_inputs(file_path="")

    def test_validate_inputs_path_traversal_file_path(self):
        """Test validation with path traversal in file_path"""
        with pytest.raises(
            PythonSecurityError, match="Path traversal attempt detected"
        ):
            _validate_inputs(file_path="../etc/passwd")

    def test_validate_inputs_all_valid(self):
        """Test validation with all valid inputs"""
        _validate_inputs(
            code="print('test')",
            timeout=10,
            filename="test.py",
            file_path="/tmp/test.py",
        )
        # Should not raise


class TestCreateSafeGlobals:
    """Test safe globals creation"""

    def test_create_safe_globals_structure(self):
        """Test that safe globals has correct structure"""
        safe_globals = _create_safe_globals()
        assert "__builtins__" in safe_globals
        assert "__name__" in safe_globals
        assert safe_globals["__name__"] == "__main__"

    def test_create_safe_globals_restricted_builtins(self):
        """Test that dangerous builtins are removed"""
        safe_globals = _create_safe_globals()
        builtins = safe_globals["__builtins__"]

        # These should be removed
        assert "eval" not in builtins
        assert "exec" not in builtins
        assert "compile" not in builtins
        assert "execfile" not in builtins

    def test_create_safe_globals_safe_builtins_present(self):
        """Test that safe builtins are still present"""
        safe_globals = _create_safe_globals()
        builtins = safe_globals["__builtins__"]

        # These should still be available
        assert "print" in builtins
        assert "len" in builtins
        assert "range" in builtins
        assert "str" in builtins

    def test_create_safe_globals_with_dict_builtins(self):
        """Test safe globals creation when __builtins__ is a dict"""
        # This tests the branch where __builtins__ is already a dict
        safe_globals = _create_safe_globals()
        assert isinstance(safe_globals["__builtins__"], dict)


class TestTimeLimit:
    """Test timeout enforcement"""

    def test_time_limit_success(self):
        """Test that code completes within time limit"""
        with _time_limit(5):
            result = 1 + 1
        assert result == 2

    def test_time_limit_timeout(self):
        """Test that timeout is enforced"""
        import time

        with pytest.raises(TimeoutError, match="exceeded"):
            with _time_limit(1):
                time.sleep(2)

    def test_time_limit_in_worker_thread(self):
        """Test timeout in worker thread"""
        import time

        def worker():
            with pytest.raises(TimeoutError):
                with _time_limit(1):
                    time.sleep(2)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()

    def test_time_limit_cleanup_on_success(self):
        """Test that cleanup happens on successful execution"""
        with _time_limit(5):
            pass
        # Should complete without issues


class TestCaptureExecutionOutput:
    """Test output capture during execution"""

    def test_capture_execution_output_success(self):
        """Test successful output capture"""
        code = "print('Hello World')"
        safe_globals = _create_safe_globals()
        stdout_file, stderr_file = _capture_execution_output(code, safe_globals, 10)
        assert Path(stdout_file).read_text() == "Hello World\n"
        # stderr_file is a path to an empty file
        assert Path(stderr_file).read_text() == ""

    def test_capture_execution_output_stderr(self):
        """Test stderr capture"""
        code = "import sys\nsys.stderr.write('Error message\\n')"
        safe_globals = _create_safe_globals()
        stdout_file, stderr_file = _capture_execution_output(code, safe_globals, 10)
        # stderr has actual content
        assert Path(stderr_file).read_text() == "Error message\n"

    def test_capture_execution_output_timeout(self):
        """Test timeout during execution"""
        code = "import time\nwhile True: time.sleep(0.1)"
        safe_globals = _create_safe_globals()
        with pytest.raises(TimeoutError):
            _capture_execution_output(code, safe_globals, 1)

    def test_capture_execution_output_with_custom_argv(self):
        """Test execution with custom sys.argv"""
        code = "import sys\nprint(sys.argv)"
        safe_globals = _create_safe_globals()
        stdout_file, stderr_file = _capture_execution_output(
            code, safe_globals, 10, argv=["script.py", "arg1", "arg2"]
        )
        stdout_content = Path(stdout_file).read_text() if stdout_file else ""
        assert "script.py" in stdout_content
        assert "arg1" in stdout_content
        assert "arg2" in stdout_content

    def test_capture_execution_output_restores_argv(self):
        """Test that sys.argv is restored after execution"""
        import sys

        original_argv = sys.argv.copy()
        code = "print('test')"
        safe_globals = _create_safe_globals()
        _capture_execution_output(code, safe_globals, 10, argv=["custom.py"])
        assert sys.argv == original_argv

    def test_capture_execution_output_with_exception(self):
        """Test that argv is restored even on exception"""
        import sys

        original_argv = sys.argv.copy()
        code = "raise ValueError('test error')"
        safe_globals = _create_safe_globals()
        with pytest.raises(ValueError):
            _capture_execution_output(code, safe_globals, 10)
        assert sys.argv == original_argv


class TestExecuteWithoutCapture:
    """Test execution without output capture"""

    def test_execute_without_capture_success(self):
        """Test successful execution without capture"""
        code = "x = 1 + 1"
        safe_globals = _create_safe_globals()
        _execute_without_capture(code, safe_globals, 10)
        # Should complete without error

    def test_execute_without_capture_timeout(self):
        """Test timeout during execution without capture"""
        code = "import time\nwhile True: time.sleep(0.1)"
        safe_globals = _create_safe_globals()
        with pytest.raises(TimeoutError):
            _execute_without_capture(code, safe_globals, 1)

    def test_execute_without_capture_with_custom_argv(self):
        """Test execution without capture with custom argv"""
        code = "import sys\nassert sys.argv == ['test.py', 'arg1']"
        safe_globals = _create_safe_globals()
        _execute_without_capture(code, safe_globals, 10, argv=["test.py", "arg1"])
        # Should complete without error

    def test_execute_without_capture_restores_argv(self):
        """Test that sys.argv is restored after execution"""
        import sys

        original_argv = sys.argv.copy()
        code = "x = 1"
        safe_globals = _create_safe_globals()
        _execute_without_capture(code, safe_globals, 10, argv=["custom.py"])
        assert sys.argv == original_argv

    def test_execute_without_capture_with_exception(self):
        """Test that argv is restored even on exception"""
        import sys

        original_argv = sys.argv.copy()
        code = "raise RuntimeError('test error')"
        safe_globals = _create_safe_globals()
        with pytest.raises(RuntimeError):
            _execute_without_capture(code, safe_globals, 10)
        assert sys.argv == original_argv


class TestValidateTimeout:
    """Test timeout validation"""

    def test_validate_timeout_valid(self):
        """Test validation with valid timeout"""
        _validate_timeout(10)
        _validate_timeout(MAX_TIMEOUT)
        # Should not raise

    def test_validate_timeout_zero(self):
        """Test validation with zero timeout"""
        with pytest.raises(ValueError, match="Invalid timeout"):
            _validate_timeout(0)

    def test_validate_timeout_negative(self):
        """Test validation with negative timeout"""
        with pytest.raises(ValueError, match="Invalid timeout"):
            _validate_timeout(-1)

    def test_validate_timeout_exceeds_max(self):
        """Test validation with timeout exceeding maximum"""
        with pytest.raises(ValueError, match="Invalid timeout"):
            _validate_timeout(MAX_TIMEOUT + 1)


class TestReadFileSafely:
    """Test safe file reading"""

    def setup_method(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def teardown_method(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_read_file_safely_success(self):
        """Test successful file reading"""
        test_file = Path(self.test_dir) / "test.py"
        test_file.write_text("print('hello')")
        content = _read_file_safely(str(test_file))
        assert content == "print('hello')"

    def test_read_file_safely_relative_path(self):
        """Test reading file with relative path"""
        test_file = Path(self.test_dir) / "test.py"
        test_file.write_text("print('hello')")
        # Change to test directory and use relative path
        content = _read_file_safely("test.py")
        assert content == "print('hello')"

    def test_read_file_safely_not_found(self):
        """Test reading non-existent file"""
        with pytest.raises(FileNotFoundError, match="File not found"):
            _read_file_safely("nonexistent.py")

    def test_read_file_safely_permission_error(self):
        """Test reading file with permission error"""
        test_file = Path(self.test_dir) / "test.py"
        test_file.write_text("print('hello')")
        # Make file unreadable
        os.chmod(test_file, 0o000)
        try:
            with pytest.raises(PermissionError):
                _read_file_safely(str(test_file))
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, 0o644)

    def test_read_file_safely_with_base_dir(self):
        """Test reading file with BASE_DIR resolution"""
        # This tests the branch where file is resolved using BASE_DIR
        with patch("aria.tools.development._internals.logger"):
            # Create a file that doesn't exist in current dir
            # but might be resolved with BASE_DIR
            with pytest.raises(FileNotFoundError):
                _read_file_safely("definitely_nonexistent_file.py")


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_code_execution(self):
        """Test execution of empty code"""
        code = ""
        safe_globals = _create_safe_globals()
        stdout_file, stderr_file = _capture_execution_output(code, safe_globals, 10)
        # Files are always created, even if empty
        assert Path(stdout_file).read_text() == ""
        assert Path(stderr_file).read_text() == ""

    def test_code_with_imports(self):
        """Test that imports work in safe globals"""
        code = "import math\nprint(math.pi)"
        safe_globals = _create_safe_globals()
        stdout_file, stderr_file = _capture_execution_output(code, safe_globals, 10)
        content = Path(stdout_file).read_text() if stdout_file else ""
        assert "3.14" in content

    def test_code_with_multiple_statements(self):
        """Test execution of code with multiple statements"""
        code = """
x = 10
y = 20
z = x + y
print(z)
"""
        safe_globals = _create_safe_globals()
        stdout_file, stderr_file = _capture_execution_output(code, safe_globals, 10)
        content = Path(stdout_file).read_text() if stdout_file else ""
        assert "30" in content

    def test_validate_inputs_with_none_values(self):
        """Test validation with None values (should be allowed)"""
        _validate_inputs(code=None, timeout=None, filename=None, file_path=None)
        # Should not raise

    def test_safe_json_with_nested_data(self):
        """Test JSON serialization with nested structures"""
        data = {
            "level1": {"level2": {"level3": {"value": "deep"}}},
            "list": [1, 2, 3],
        }
        result = safe_json(data)
        parsed = json.loads(result)
        assert parsed == data
