"""Contract verification tests for public exports vs documented signatures.

Run with: pytest src/aria/tools/tests/test_contract_verification.py -v
"""

import inspect

from aria.tools import tool_success_response


class TestFilesPackageContract:
    """Verify files package exports match their implementations."""

    def test_files_write_operations_have_expected_signatures(self):
        """Verify write operation functions have documented parameter names."""
        from aria.tools.files.write_operations import edit_file, write_file

        # write_file: reason, file_name, contents, mode
        sig = inspect.signature(write_file)
        params = list(sig.parameters.keys())
        assert "reason" in params
        assert "file_name" in params
        assert "contents" in params, "write_file should have 'contents' parameter"
        assert "mode" in params, "write_file should have 'mode' parameter"

        # edit_file: reason, file_name, offset, length, new_lines
        sig = inspect.signature(edit_file)
        params = list(sig.parameters.keys())
        assert "reason" in params
        assert "file_name" in params
        assert "offset" in params, "edit_file should have 'offset' parameter"

    def test_files_management_operations_have_expected_signatures(self):
        """Verify file management functions have documented parameter names."""
        from aria.tools.files import file_management

        # copy_file should have src, dest
        sig = inspect.signature(file_management.copy_file)
        params = list(sig.parameters.keys())
        assert "src" in params or "source" in params, (
            "copy_file should have 'src' or 'source' parameter"
        )
        assert "dest" in params or "destination" in params, (
            "copy_file should have 'dest' or 'destination' parameter"
        )


class TestReasoningPackageContract:
    """Verify reasoning package exports match their implementations."""

    def test_reasoning_has_no_conclusion_parameter(self):
        """Issue #12: reasoning should NOT have a 'conclusion' parameter.

        Previous docs incorrectly documented a 'conclusion' argument.
        """
        from aria.tools.reasoning import reasoning

        sig = inspect.signature(reasoning)
        params = list(sig.parameters.keys())
        assert "conclusion" not in params, (
            "reasoning should not have a 'conclusion' parameter. "
            "This was a documentation bug."
        )


class TestToolSuccessResponseContract:
    """Verify tool_success_response handles reason correctly."""

    def test_tool_success_response_falls_back_for_empty_reason(self):
        """Verify tool_success_response handles empty reason gracefully."""
        response_str = tool_success_response(
            tool="test_tool",
            reason="",
            data={"result": "success"},
        )
        import json

        response = json.loads(response_str)
        assert response["reason"] == "unspecified_test_tool_operation", (
            "tool_success_response should use fallback reason when empty"
        )


class TestPathContractConsistency:
    """Verify path handling is consistent across file tools."""

    def test_secure_resolve_path_does_not_enforce_base_dir_by_default(self):
        """enforce_base_dir defaults to False — workspace confinement is opt-in."""
        from aria.tools.files._internals import _secure_resolve_path

        sig = inspect.signature(_secure_resolve_path)
        params = sig.parameters

        enforce_param = params.get("enforce_base_dir")
        if enforce_param:
            default = enforce_param.default
            msg = "enforce_base_dir default should be False (opt-in confinement)"
            assert default is False, msg
