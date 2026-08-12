"""Tests for AppState validation logic in :mod:`aria.web.state`."""

from __future__ import annotations

import pytest

from aria.web.state import (
    _REQUIRED_FIELDS,
    AppState,
    AppStateNotInitializedError,
)

# Sentinel object used as a non-None placeholder.  We use model_construct()
# to bypass Pydantic type validation so we can test the *logic* of
# is_initialized / validate_initialized without importing heavy dependencies.
_SENTINEL = object()


def _fully_initialized_state() -> AppState:
    """Return an AppState with all required fields populated via sentinels."""
    return AppState.model_construct(
        llm=_SENTINEL,
        embeddings=_SENTINEL,
        vector_db=_SENTINEL,
        agents_workflow=_SENTINEL,
        db_engine=_SENTINEL,
        startup_complete=True,
    )


class TestRequiredFieldsConsistency:
    """Ensure _REQUIRED_FIELDS stays in sync with the AppState model."""

    def test_all_required_fields_exist_on_model(self) -> None:
        state = AppState()
        for field in _REQUIRED_FIELDS:
            assert hasattr(state, field), (
                f"_REQUIRED_FIELDS references '{field}' "
                f"which does not exist on AppState"
            )


class TestIsInitialized:
    """Tests for AppState.is_initialized()."""

    def test_fresh_state_is_not_initialized(self) -> None:
        state = AppState()
        assert state.is_initialized() is False

    def test_fully_populated_state_is_initialized(self) -> None:
        state = _fully_initialized_state()
        assert state.is_initialized() is True

    @pytest.mark.parametrize("field", _REQUIRED_FIELDS)
    def test_missing_single_required_field(self, field: str) -> None:
        state = _fully_initialized_state()
        object.__setattr__(state, field, None)
        assert state.is_initialized() is False

    def test_startup_complete_false_means_not_initialized(self) -> None:
        state = _fully_initialized_state()
        object.__setattr__(state, "startup_complete", False)
        assert state.is_initialized() is False

    def test_optional_fields_do_not_affect_initialization(self) -> None:
        """prompt_enhancer, vllm_manager, browser_manager are optional."""
        state = _fully_initialized_state()
        object.__setattr__(state, "prompt_enhancer", None)
        object.__setattr__(state, "vllm_manager", None)
        object.__setattr__(state, "browser_manager", None)
        assert state.is_initialized() is True


class TestValidateInitialized:
    """Tests for AppState.validate_initialized()."""

    def test_raises_on_fresh_state(self) -> None:
        state = AppState()
        with pytest.raises(AppStateNotInitializedError):
            state.validate_initialized()

    def test_passes_on_fully_initialized_state(self) -> None:
        state = _fully_initialized_state()
        state.validate_initialized()  # should not raise

    def test_error_message_lists_missing_fields(self) -> None:
        state = AppState()
        with pytest.raises(AppStateNotInitializedError, match="llm"):
            state.validate_initialized()

    @pytest.mark.parametrize("field", _REQUIRED_FIELDS)
    def test_error_message_names_specific_missing_field(self, field: str) -> None:
        state = _fully_initialized_state()
        object.__setattr__(state, field, None)
        with pytest.raises(AppStateNotInitializedError, match=field):
            state.validate_initialized()

    def test_error_includes_startup_complete_when_only_flag_missing(
        self,
    ) -> None:
        state = _fully_initialized_state()
        object.__setattr__(state, "startup_complete", False)
        with pytest.raises(AppStateNotInitializedError, match="startup_complete"):
            state.validate_initialized()

    def test_error_lists_multiple_missing_fields(self) -> None:
        state = AppState.model_construct(
            llm=_SENTINEL,
            startup_complete=True,
        )
        with pytest.raises(AppStateNotInitializedError) as exc_info:
            state.validate_initialized()
        msg = str(exc_info.value)
        assert "embeddings" in msg
        assert "vector_db" in msg
        assert "agents_workflow" in msg
        assert "db_engine" in msg
        # llm is set, so it should NOT be listed
        assert "llm" not in msg


class TestAppStateNotInitializedError:
    """Tests for the custom exception class."""

    def test_default_message(self) -> None:
        err = AppStateNotInitializedError()
        assert "not fully initialized" in str(err).lower()
