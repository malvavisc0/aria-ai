from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from aria.web import session as session_module


class TestExtractImageData:
    """Tests for extract_image_data()."""

    @staticmethod
    def test_returns_base64_for_image_elements(tmp_path: Path) -> None:
        img_file = tmp_path / "photo.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        message = SimpleNamespace(
            elements=[
                SimpleNamespace(
                    path=str(img_file),
                    mime="image/png",
                    name="photo.png",
                ),
            ],
        )

        result = session_module.extract_image_data(message)

        assert len(result) == 1
        assert result[0]["mime_type"] == "image/png"
        assert result[0]["name"] == "photo.png"
        assert isinstance(result[0]["base64"], str)
        assert len(result[0]["base64"]) > 0

    @staticmethod
    def test_skips_non_image_elements(tmp_path: Path) -> None:
        pdf_file = tmp_path / "doc.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        message = SimpleNamespace(
            elements=[
                SimpleNamespace(
                    path=str(pdf_file),
                    mime="application/pdf",
                    name="doc.pdf",
                ),
            ],
        )

        result = session_module.extract_image_data(message)
        assert result == []

    @staticmethod
    def test_detects_image_by_extension_when_mime_missing(
        tmp_path: Path,
    ) -> None:
        img_file = tmp_path / "shot.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

        message = SimpleNamespace(
            elements=[
                SimpleNamespace(
                    path=str(img_file),
                    mime="",
                    name="shot.jpg",
                ),
            ],
        )

        result = session_module.extract_image_data(message)

        assert len(result) == 1
        assert result[0]["mime_type"] == "image/jpg"

    @staticmethod
    def test_handles_multiple_images(tmp_path: Path) -> None:
        img1 = tmp_path / "a.png"
        img2 = tmp_path / "b.webp"
        img1.write_bytes(b"\x89PNG" + b"\x00" * 10)
        img2.write_bytes(b"RIFF" + b"\x00" * 10)

        message = SimpleNamespace(
            elements=[
                SimpleNamespace(path=str(img1), mime="image/png", name="a.png"),
                SimpleNamespace(path=str(img2), mime="image/webp", name="b.webp"),
            ],
        )

        result = session_module.extract_image_data(message)

        assert len(result) == 2
        assert result[0]["name"] == "a.png"
        assert result[1]["name"] == "b.webp"

    @staticmethod
    def test_returns_empty_for_no_elements() -> None:
        message = SimpleNamespace(elements=[])
        assert session_module.extract_image_data(message) == []

    @staticmethod
    def test_returns_empty_when_elements_is_none() -> None:
        message = SimpleNamespace(elements=None)
        assert session_module.extract_image_data(message) == []

    @staticmethod
    def test_skips_element_without_path() -> None:
        message = SimpleNamespace(
            elements=[
                SimpleNamespace(path=None, mime="image/png", name="no.png"),
            ],
        )

        result = session_module.extract_image_data(message)
        assert result == []

    @staticmethod
    def test_handles_unreadable_file_gracefully(tmp_path: Path) -> None:
        """When the image file doesn't exist, a warning is logged and skipped."""
        message = SimpleNamespace(
            elements=[
                SimpleNamespace(
                    path=str(tmp_path / "missing.png"),
                    mime="image/png",
                    name="missing.png",
                ),
            ],
        )

        result = session_module.extract_image_data(message)
        assert result == []


def test_extract_file_paths_skips_image_elements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Image elements should be excluded from file_paths output."""
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    monkeypatch.setattr(session_module.UploadsConfig, "path", uploads_dir)

    img_file = tmp_path / "photo.png"
    img_file.write_bytes(b"\x89PNG" + b"\x00" * 10)
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    message = SimpleNamespace(
        thread_id="t1",
        elements=[
            SimpleNamespace(path=str(img_file), mime="image/png", name="photo.png"),
            SimpleNamespace(
                path=str(pdf_file),
                mime="application/pdf",
                name="doc.pdf",
            ),
        ],
    )

    paths = session_module.extract_file_paths(message)

    assert len(paths) == 1
    assert "doc.pdf" in paths[0]


def test_extract_file_paths_uses_unique_destination_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    monkeypatch.setattr(session_module.UploadsConfig, "path", uploads_dir)

    src_a = tmp_path / "source-a.txt"
    src_b = tmp_path / "source-b.txt"
    src_a.write_text("first", encoding="utf-8")
    src_b.write_text("second", encoding="utf-8")

    message = SimpleNamespace(
        thread_id="thread-123",
        elements=[
            SimpleNamespace(path=str(src_a), name="report.txt"),
            SimpleNamespace(path=str(src_b), name="report.txt"),
        ],
    )

    paths = session_module.extract_file_paths(message)

    assert len(paths) == 2
    assert paths[0] != paths[1]
    assert Path(paths[0]).read_text(encoding="utf-8") == "first"
    assert Path(paths[1]).read_text(encoding="utf-8") == "second"


@pytest.mark.asyncio
async def test_restore_chat_history_sorts_root_messages_chronologically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages = []

    class _FakeMemory:
        async def aput_messages(self, messages):
            captured_messages.extend(messages)

    monkeypatch.setattr(
        session_module, "create_memory", lambda thread_id: _FakeMemory()
    )

    thread = {
        "id": "thread-1",
        "name": "Example",
        "steps": [
            {
                "id": "2",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:01Z",
                "type": "assistant_message",
                "output": "second",
            },
            {
                "id": "1",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:00Z",
                "type": "user_message",
                "output": "first",
            },
        ],
    }

    await session_module.restore_chat_history(thread)

    assert [message.content for message in captured_messages] == [
        "first",
        "second",
    ]


@pytest.mark.asyncio
async def test_restore_chat_history_includes_child_assistant_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assistant messages with parentId set must still be restored.

    get_thread() returns the raw parent-child tree where assistant
    messages are children of user messages (parentId != None).
    """
    captured_messages = []

    class _FakeMemory:
        async def aput_messages(self, messages):
            captured_messages.extend(messages)

    monkeypatch.setattr(
        session_module, "create_memory", lambda thread_id: _FakeMemory()
    )

    thread = {
        "id": "thread-child",
        "name": "Child test",
        "steps": [
            {
                "id": "u1",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:00Z",
                "type": "user_message",
                "output": "Hello",
            },
            {
                "id": "a1",
                "parentId": "u1",
                "createdAt": "2026-03-27T10:00:01Z",
                "type": "assistant_message",
                "output": "Hi there!",
            },
            {
                "id": "u2",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:02Z",
                "type": "user_message",
                "output": "How are you?",
            },
            {
                "id": "a2",
                "parentId": "u2",
                "createdAt": "2026-03-27T10:00:03Z",
                "type": "assistant_message",
                "output": "I'm great!",
            },
        ],
    }

    await session_module.restore_chat_history(thread)

    assert [m.content for m in captured_messages] == [
        "Hello",
        "Hi there!",
        "How are you?",
        "I'm great!",
    ]


@pytest.mark.asyncio
async def test_restore_chat_history_sanitises_consecutive_same_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consecutive messages of the same role should collapse to the last."""
    captured_messages = []

    class _FakeMemory:
        async def aput_messages(self, messages):
            captured_messages.extend(messages)

    monkeypatch.setattr(
        session_module, "create_memory", lambda thread_id: _FakeMemory()
    )

    thread = {
        "id": "thread-dup",
        "name": "Dup test",
        "steps": [
            {
                "id": "u1",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:00Z",
                "type": "user_message",
                "output": "first user",
            },
            {
                "id": "u2",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:01Z",
                "type": "user_message",
                "output": "second user",
            },
            {
                "id": "a1",
                "parentId": "u2",
                "createdAt": "2026-03-27T10:00:02Z",
                "type": "assistant_message",
                "output": "reply",
            },
        ],
    }

    await session_module.restore_chat_history(thread)

    # The first user message is dropped (consecutive duplicate → keep last).
    assert [m.content for m in captured_messages] == [
        "second user",
        "reply",
    ]


@pytest.mark.asyncio
async def test_restore_chat_history_drops_trailing_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trailing user message (no assistant reply) must be dropped."""
    captured_messages = []

    class _FakeMemory:
        async def aput_messages(self, messages):
            captured_messages.extend(messages)

    monkeypatch.setattr(
        session_module, "create_memory", lambda thread_id: _FakeMemory()
    )

    thread = {
        "id": "thread-trailing",
        "name": "Trailing test",
        "steps": [
            {
                "id": "u1",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:00Z",
                "type": "user_message",
                "output": "Hello",
            },
            {
                "id": "a1",
                "parentId": "u1",
                "createdAt": "2026-03-27T10:00:01Z",
                "type": "assistant_message",
                "output": "Hi!",
            },
            {
                "id": "u2",
                "parentId": None,
                "createdAt": "2026-03-27T10:00:02Z",
                "type": "user_message",
                "output": "unanswered",
            },
        ],
    }

    await session_module.restore_chat_history(thread)

    # Trailing user message is dropped to maintain alternation.
    assert [m.content for m in captured_messages] == [
        "Hello",
        "Hi!",
    ]


class TestConvertDocumentsToMarkdown:
    """Tests for convert_documents_to_markdown()."""

    @staticmethod
    def test_converts_pdf_to_markdown(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            session_module.WorkspaceConfig, "path", tmp_path / "workspace"
        )

        pdf_file = tmp_path / "report.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        # Mock MarkItDown
        class FakeResult:
            text_content = "# Report\n\nSome content here."

        class FakeMarkItDown:
            def convert(self, path):
                return FakeResult()

        monkeypatch.setattr(
            "aria.web.session.MarkItDown",
            FakeMarkItDown,
            raising=False,
        )
        # Patch the import inside the function
        import aria.web.session as mod

        original_fn = mod.convert_documents_to_markdown

        def patched_convert(file_paths):
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "markitdown":
                    import types

                    m = types.ModuleType("markitdown")
                    m.MarkItDown = FakeMarkItDown
                    return m
                return real_import(name, *args, **kwargs)

            monkeypatch.setattr(builtins, "__import__", fake_import)
            try:
                return original_fn(file_paths)
            finally:
                monkeypatch.setattr(builtins, "__import__", real_import)

        results = patched_convert([str(pdf_file)])

        assert len(results) == 1
        assert results[0]["markdown_path"] is not None
        assert results[0]["name"] == "report.pdf"
        assert results[0]["lines"] > 0
        assert results[0]["chars"] > 0
        assert results[0]["error"] is None
        assert Path(results[0]["markdown_path"]).exists()

    @staticmethod
    def test_skips_unsupported_extensions(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            session_module.WorkspaceConfig, "path", tmp_path / "workspace"
        )

        bin_file = tmp_path / "data.bin"
        bin_file.write_bytes(b"\x00\x01\x02")

        results = session_module.convert_documents_to_markdown([str(bin_file)])

        assert len(results) == 1
        assert results[0]["markdown_path"] is None
        assert results[0]["error"] is None

    @staticmethod
    def test_returns_empty_for_empty_input() -> None:
        assert session_module.convert_documents_to_markdown([]) == []

    @staticmethod
    def test_handles_conversion_failure_gracefully(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            session_module.WorkspaceConfig, "path", tmp_path / "workspace"
        )

        pdf_file = tmp_path / "bad.pdf"
        pdf_file.write_bytes(b"not a real pdf")

        results = session_module.convert_documents_to_markdown([str(pdf_file)])

        assert len(results) == 1
        # Either converts successfully or reports error gracefully
        r = results[0]
        assert r["name"] == "bad.pdf"
        # If markitdown isn't installed, it'll error; if it is, it may succeed or fail
        assert r["markdown_path"] is not None or r["error"] is not None

    @staticmethod
    def _patched_convert(file_paths, monkeypatch):
        """Run convert_documents_to_markdown with a mocked MarkItDown import."""

        class FakeResult:
            def __init__(self, text):
                self.text_content = text

        class FakeMarkItDown:
            def convert(self, path):
                content = Path(path).read_text(encoding="utf-8")
                return FakeResult(content)

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "markitdown":
                import types

                m = types.ModuleType("markitdown")
                m.MarkItDown = FakeMarkItDown
                return m
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        try:
            return session_module.convert_documents_to_markdown(file_paths)
        finally:
            monkeypatch.setattr(builtins, "__import__", real_import)

    @staticmethod
    def test_converts_txt_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(
            session_module.WorkspaceConfig, "path", tmp_path / "workspace"
        )

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Hello, world!\nLine two.")

        results = TestConvertDocumentsToMarkdown._patched_convert(
            [str(txt_file)], monkeypatch
        )

        assert len(results) == 1
        r = results[0]
        assert r["name"] == "notes.txt"
        assert r["markdown_path"] is not None
        assert r["error"] is None
        assert r["lines"] == 2
        assert r["chars"] == 23
        assert Path(r["markdown_path"]).exists()
        assert Path(r["markdown_path"]).read_text(encoding="utf-8") == (
            "Hello, world!\nLine two."
        )

    @staticmethod
    def test_converts_json_file(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            session_module.WorkspaceConfig, "path", tmp_path / "workspace"
        )

        json_file = tmp_path / "data.json"
        json_file.write_text('{"key": "value", "count": 42}')

        results = TestConvertDocumentsToMarkdown._patched_convert(
            [str(json_file)], monkeypatch
        )

        assert len(results) == 1
        r = results[0]
        assert r["name"] == "data.json"
        assert r["markdown_path"] is not None
        assert r["error"] is None
        assert r["lines"] > 0

    @staticmethod
    def test_converts_python_file(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            session_module.WorkspaceConfig, "path", tmp_path / "workspace"
        )

        py_file = tmp_path / "script.py"
        py_file.write_text("def hello():\n    print('hi')\n\nhello()\n")

        results = TestConvertDocumentsToMarkdown._patched_convert(
            [str(py_file)], monkeypatch
        )

        assert len(results) == 1
        r = results[0]
        assert r["name"] == "script.py"
        assert r["markdown_path"] is not None
        assert r["error"] is None
        assert r["lines"] > 0

    @staticmethod
    def test_converts_yaml_file(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            session_module.WorkspaceConfig, "path", tmp_path / "workspace"
        )

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("name: aria\nversion: 1\n")

        results = TestConvertDocumentsToMarkdown._patched_convert(
            [str(yaml_file)], monkeypatch
        )

        assert len(results) == 1
        r = results[0]
        assert r["name"] == "config.yaml"
        assert r["markdown_path"] is not None
        assert r["error"] is None

    @staticmethod
    def test_text_extensions_in_markitdown_set() -> None:
        """All common text extensions should be recognised for conversion."""
        expected = {
            ".txt",
            ".md",
            ".rst",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".toml",
            ".py",
            ".js",
            ".ts",
            ".sh",
            ".log",
            ".ini",
            ".cfg",
        }
        assert expected.issubset(session_module._MARKITDOWN_EXTENSIONS)


def test_sanitize_chat_history_empty() -> None:
    assert session_module._sanitize_chat_history([]) == []


def test_sanitize_chat_history_already_alternating() -> None:
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="a"),
        ChatMessage(role=MessageRole.ASSISTANT, content="b"),
        ChatMessage(role=MessageRole.USER, content="c"),
        ChatMessage(role=MessageRole.ASSISTANT, content="d"),
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert [m.content for m in result] == ["a", "b", "c", "d"]


def test_sanitize_chat_history_leading_assistant_dropped() -> None:
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.ASSISTANT, content="orphan"),
        ChatMessage(role=MessageRole.USER, content="a"),
        ChatMessage(role=MessageRole.ASSISTANT, content="b"),
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert [m.content for m in result] == ["a", "b"]


def test_sanitize_chat_history_trailing_user_dropped() -> None:
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="a"),
        ChatMessage(role=MessageRole.ASSISTANT, content="b"),
        ChatMessage(role=MessageRole.USER, content="dangling"),
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert [m.content for m in result] == ["a", "b"]


def _assistant_with_tool_calls(n: int, content: str = "") -> "ChatMessage":  # noqa: F821
    from llama_index.core.base.llms.types import (
        ChatMessage,
        MessageRole,
        TextBlock,
        ToolCallBlock,
    )

    blocks: list = [TextBlock(text=content)] if content else []
    for i in range(n):
        blocks.append(
            ToolCallBlock(
                tool_call_id=f"call_{i}",
                tool_name=f"tool_{i}",
                tool_kwargs="{}",
            )
        )
    return ChatMessage(role=MessageRole.ASSISTANT, blocks=blocks)


def _tool_message(call_id: str, content: str = "ok") -> "ChatMessage":  # noqa: F821
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    return ChatMessage(
        role=MessageRole.TOOL,
        content=content,
        additional_kwargs={"tool_call_id": call_id},
    )


def test_sanitize_preserves_parallel_tool_calls() -> None:
    """Regression: two parallel tool calls must keep BOTH tool responses.

    Previously consecutive TOOL messages were collapsed into one, leaving
    2 tool calls with 1 response → Mistral 400.
    """
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="q"),
        _assistant_with_tool_calls(2),
        _tool_message("call_0", "r0"),
        _tool_message("call_1", "r1"),
        ChatMessage(role=MessageRole.ASSISTANT, content="final"),
    ]
    result = session_module._sanitize_chat_history(msgs)

    tool_msgs = [m for m in result if m.role == MessageRole.TOOL]
    assert len(tool_msgs) == 2
    # call count == response count
    assistant_calls = session_module._message_tool_call_count(result[1])
    assert assistant_calls == len(tool_msgs)
    assert result[-1].content == "final"


def test_sanitize_drops_dangling_tool_call_group() -> None:
    """Assistant with tool calls but no following tool messages → dropped.

    The trailing user message is then also dropped (no assistant reply
    follows), so the whole history collapses to empty — the important
    invariant is that no unbalanced tool group survives.
    """
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="q"),
        _assistant_with_tool_calls(2),  # failed mid-turn, no tool results
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert all(m.role != MessageRole.TOOL for m in result)
    assert all(session_module._message_tool_call_count(m) == 0 for m in result)


def test_sanitize_drops_dangling_tool_call_group_keeps_prior_turn() -> None:
    """A complete prior turn survives even when the latest turn dangles."""
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="q1"),
        ChatMessage(role=MessageRole.ASSISTANT, content="a1"),
        ChatMessage(role=MessageRole.USER, content="q2"),
        _assistant_with_tool_calls(2),  # failed mid-turn, no tool results
    ]
    result = session_module._sanitize_chat_history(msgs)
    # Dangling tool group + its trailing user turn are dropped; the first
    # complete user/assistant turn remains and is balanced.
    assert [m.content for m in result] == ["q1", "a1"]
    assert all(m.role != MessageRole.TOOL for m in result)


def test_sanitize_drops_partial_tool_call_group() -> None:
    """2 tool calls but only 1 response → whole group dropped."""
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="q"),
        _assistant_with_tool_calls(2),
        _tool_message("call_0", "r0"),
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert all(m.role != MessageRole.TOOL for m in result)
    assert all(session_module._message_tool_call_count(m) == 0 for m in result)


def test_sanitize_drops_orphan_tool_message() -> None:
    """A tool message with no preceding assistant tool-call is dropped."""
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="q"),
        _tool_message("call_x", "orphan"),
        ChatMessage(role=MessageRole.ASSISTANT, content="final"),
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert all(m.role != MessageRole.TOOL for m in result)
    assert [m.content for m in result] == ["q", "final"]


def test_sanitize_counts_additional_kwargs_tool_calls() -> None:
    """Tool calls in additional_kwargs (no blocks) are counted correctly."""
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    assistant = ChatMessage(
        role=MessageRole.ASSISTANT,
        additional_kwargs={"tool_calls": [{"id": "a"}, {"id": "b"}]},
    )
    assert session_module._message_tool_call_count(assistant) == 2

    msgs = [
        ChatMessage(role=MessageRole.USER, content="q"),
        assistant,
        _tool_message("a"),
        _tool_message("b"),
        ChatMessage(role=MessageRole.ASSISTANT, content="final"),
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert len([m for m in result if m.role == MessageRole.TOOL]) == 2


def test_sanitize_keeps_single_tool_call_turn() -> None:
    from llama_index.core.base.llms.types import ChatMessage, MessageRole

    msgs = [
        ChatMessage(role=MessageRole.USER, content="q"),
        _assistant_with_tool_calls(1),
        _tool_message("call_0"),
        ChatMessage(role=MessageRole.ASSISTANT, content="final"),
    ]
    result = session_module._sanitize_chat_history(msgs)
    assert len(result) == 4
    assert len([m for m in result if m.role == MessageRole.TOOL]) == 1
