import json
import os
import shutil
import tempfile
from pathlib import Path

from aria.tools.development import python


class TestPythonRunner:
    """Test suite for unified python tool."""

    def setup_method(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.test_dir)

        # Save original working directory
        self.original_cwd = os.getcwd()
        # Change to test directory so file I/O works
        os.chdir(self.test_dir)

        # Create a test Python file
        self.test_file = self.base_dir / "test_script.py"
        self.test_file.write_text("print('Hello from test file')\n")

    def teardown_method(self):
        """Clean up test environment"""
        # Restore original working directory
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --- check_only: code ---

    def test_check_syntax_valid_code(self):
        """Test syntax validation with valid code"""
        code = "def foo():\n    return True\n"
        result = python("Testing syntax validation", code=code, check_only=True)
        data = json.loads(result)

        assert data["data"]["tool"] == "python"
        assert data["data"]["result"]["valid"] is True
        assert data["data"]["result"]["message"] == "Syntax is valid"
        assert data["context"]["filename"] == "<block>"
        assert data["context"]["source"] == "code"

    def test_check_syntax_invalid_code(self):
        """Test syntax validation with invalid code"""
        code = "def foo()\n    return True\n"  # Missing colon
        result = python("Testing invalid syntax", code=code, check_only=True)
        data = json.loads(result)

        assert data["data"]["tool"] == "python"
        assert data["data"]["result"]["valid"] is False
        assert data["data"]["result"]["error_type"] == "SyntaxError"
        assert data["data"]["result"]["message"] == "expected ':'"
        assert data["data"]["result"]["line_number"] == 1
        assert data["context"]["source"] == "code"

    def test_check_syntax_edge_cases(self):
        """Test syntax checking edge cases"""
        # Empty code
        result = python("Testing empty code", code="", check_only=True)
        data = json.loads(result)
        assert data["data"]["result"]["valid"] is True

        # Code with comments only
        result = python(
            "Testing comments", code="# This is a comment\n", check_only=True
        )
        data = json.loads(result)
        assert data["data"]["result"]["valid"] is True

        # Code with multi-line strings
        result = python(
            "Testing multiline",
            code='text = """Multi\nline\nstring"""',
            check_only=True,
        )
        data = json.loads(result)
        assert data["data"]["result"]["valid"] is True

    # --- check_only: file ---

    def test_check_syntax_valid_file(self):
        """Test file syntax validation with valid file"""
        result = python(
            "Testing file syntax",
            file=str(self.test_file),
            check_only=True,
        )
        data = json.loads(result)

        assert data["data"]["tool"] == "python"
        assert data["data"]["result"]["valid"] is True
        assert data["context"]["source"] == "file"

    def test_check_syntax_invalid_file(self):
        """Test file syntax validation with invalid file"""
        invalid_file = self.base_dir / "invalid.py"
        invalid_file.write_text("def foo()\n    return True\n")

        result = python(
            "Testing invalid file",
            file=str(invalid_file),
            check_only=True,
        )
        data = json.loads(result)

        assert data["data"]["result"]["valid"] is False
        assert data["data"]["result"]["error_type"] == "SyntaxError"

    def test_check_syntax_nonexistent_file(self):
        """Test syntax checking of non-existent file"""
        result = python(
            "Testing nonexistent",
            file="nonexistent.py",
            check_only=True,
        )
        data = json.loads(result)
        assert data["status"] == "error"

    # --- execute: code ---

    def test_execute_code_success(self):
        """Test successful code execution"""
        code = "print('Hello World')\nresult = 42\n"
        result = python("Testing code execution", code=code, timeout=10)
        data = json.loads(result)

        assert data["data"]["tool"] == "python"
        assert data["data"]["result"]["success"] is True
        import os

        assert os.path.exists(data["data"]["result"]["stdout_file"])
        # stderr_file may be absent if empty
        if "stderr_file" in data["data"]["result"]:
            assert os.path.exists(data["data"]["result"]["stderr_file"])
        assert data["context"]["source"] == "code"
        assert data["context"]["timeout"] == 10

    def test_execute_code_error(self):
        """Test code execution with error"""
        code = "print(undefined_variable)\n"
        result = python("Testing error handling", code=code, timeout=10)
        data = json.loads(result)

        assert data["data"]["tool"] == "python"
        assert data["data"]["result"]["success"] is False
        assert data["data"]["result"]["error_type"] == "NameError"
        assert "traceback" in data["data"]["result"]

    def test_execute_code_timeout(self):
        """Test code execution timeout"""
        code = "import time\nwhile True: time.sleep(0.1)\n"
        result = python("Testing timeout", code=code, timeout=1)
        data = json.loads(result)

        assert data["data"]["result"]["success"] is False
        assert data["data"]["result"]["error_type"] == "TimeoutError"
        assert (
            "timeout" in data["data"]["result"]["message"].lower()
            or "exceeded" in data["data"]["result"]["message"].lower()
        )
        assert data["context"]["timeout"] == 1

    def test_execute_code_restricted_builtins(self):
        """Test execution with restricted builtins"""
        code = "exec('print(\"test\")')\n"
        result = python("Testing restricted builtins", code=code, timeout=10)
        data = json.loads(result)

        assert data["data"]["result"]["success"] is False
        assert data["data"]["result"]["error_type"] == "NameError"

    def test_execute_code_imports_allowed(self):
        """Test that imports are allowed"""
        code = "import math\nresult = math.sqrt(16)\nprint(result)\n"
        result = python("Testing imports", code=code, timeout=10)
        data = json.loads(result)

        assert data["data"]["result"]["success"] is True
        assert os.path.exists(data["data"]["result"]["stdout_file"])

    def test_execute_code_file_io_allowed(self):
        """Test that file I/O is allowed"""
        test_read_file = self.base_dir / "read_test.txt"
        test_read_file.write_text("Hello from file\n")

        code = (
            "with open('read_test.txt', 'r') as f:\n"
            "    content = f.read()\n"
            "print(content)\n"
        )
        result = python("Testing file I/O", code=code, timeout=10)
        data = json.loads(result)

        assert data["data"]["result"]["success"] is True
        assert (
            "Hello from file" in Path(data["data"]["result"]["stdout_file"]).read_text()
        )

    def test_execute_code_with_complex_logic(self):
        """Test execution with complex logic"""
        code = """
def fibonacci(n):
    if n <= 1:
        return n
    else:
        return fibonacci(n-1) + fibonacci(n-2)

result = fibonacci(5)
print(f'Fibonacci(5) = {result}')
"""
        result = python("Testing complex logic", code=code, timeout=10)
        data = json.loads(result)

        assert data["data"]["result"]["success"] is True
        assert (
            "Fibonacci(5) = 5"
            in Path(data["data"]["result"]["stdout_file"]).read_text()
        )

    def test_execute_code_with_stderr(self):
        """Test execution with stderr output"""
        code = "import sys\nsys.stderr.write('Error message\\n')\n"
        result = python("Testing stderr", code=code, timeout=10)
        data = json.loads(result)

        assert data["data"]["result"]["success"] is True
        assert (
            Path(data["data"]["result"]["stderr_file"]).read_text() == "Error message\n"
        )

    def test_execute_code_with_security_violation(self):
        """Test that security violations are properly caught"""
        dangerous_code = [
            "eval('1+1')",
            "exec('print(\"test\")')",
            "compile('print(1)', 'test', 'exec')",
        ]

        for code in dangerous_code:
            result = python("Testing security", code=code, timeout=10)
            data = json.loads(result)
            assert data["data"]["tool"] == "python"
            # Should not succeed with dangerous code
            assert data["data"]["result"]["success"] is False

    # --- execute: file ---

    def test_execute_file_success(self):
        """Test successful file execution"""
        result = python(
            "Testing file execution",
            file=str(self.test_file),
            timeout=10,
        )
        data = json.loads(result)

        assert data["data"]["result"]["success"] is True
        assert (
            Path(data["data"]["result"]["stdout_file"]).read_text()
            == "Hello from test file\n"
        )
        assert data["context"]["source"] == "file"

    def test_execute_file_nonexistent(self):
        """Test execution of non-existent file"""
        result = python("Testing nonexistent", file="nonexistent.py", timeout=10)
        data = json.loads(result)
        assert data["status"] == "error"

    # --- validation: mutual exclusivity ---

    def test_neither_code_nor_file_raises_error(self):
        """Test that providing neither code nor file raises error"""
        result = python("Testing no input", check_only=True)
        data = json.loads(result)
        assert data["status"] == "error"

    def test_both_code_and_file_raises_error(self):
        """Test that providing both code and file raises error"""
        result = python(
            "Testing both inputs",
            code="print('hello')",
            file="test.py",
            check_only=True,
        )
        data = json.loads(result)
        assert data["status"] == "error"
