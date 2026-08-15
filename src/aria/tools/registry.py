"""Tool registry for categorized tool loading.

Categories:
- core_lite: Aria agent tools (reasoning, shell)
- files_lite: Aria agent file tools (read_file, write_file, edit_file,
              list_files, search_files)
- core: Worker tools (plan, scratchpad, shell)
- files: Worker file tools (read_file, write_file, edit_file,
         file_info, list_files, search_files, copy_file)
- ax: Unified dispatcher (web, knowledge, finance, imdb, http, dev, processes,
      documents, check, worker, mcp)
"""

from collections.abc import Callable

from llama_index.core.tools import FunctionTool
from loguru import logger

# Tool categories
CORE_LITE = "core_lite"
FILES_LITE = "files_lite"
CORE = "core"
FILES = "files"
AX = "ax"
WORKER_AX = "worker_ax"

ALL_CATEGORIES = [
    CORE,
    FILES,
    AX,
]


def _import_function(module_path: str, function_name: str) -> Callable:
    """Import a function from a module path."""
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, function_name)


def _get_core_lite_tools() -> list[FunctionTool]:
    """Aria agent core tools: reasoning + shell only."""
    from aria.tools.reasoning.functions import ReasoningSchema
    from aria.tools.shell.functions import ShellToolSchema

    tool_specs = [
        ("aria.tools.reasoning", "reasoning"),
        ("aria.tools.shell", "shell"),
    ]
    explicit_schemas = {
        "reasoning": ReasoningSchema,
        "shell": ShellToolSchema,
    }
    tools: list[FunctionTool] = []
    for mod, fn in tool_specs:
        func = _import_function(mod, fn)
        schema = explicit_schemas.get(fn)
        if schema is not None:
            tools.append(FunctionTool.from_defaults(fn=func, fn_schema=schema))
        else:
            tools.append(FunctionTool.from_defaults(fn=func))
    return tools


def _get_file_lite_tools() -> list[FunctionTool]:
    """Aria agent file tools: no file_info or copy_file."""
    from aria.tools.files.unified_read import (
        ListFilesSchema,
        ReadFileSchema,
        SearchFilesSchema,
    )
    from aria.tools.files.write_operations import (
        EditFileSchema,
        WriteFileSchema,
    )

    tool_specs = [
        ("aria.tools.files", "read_file"),
        ("aria.tools.files", "write_file"),
        ("aria.tools.files", "edit_file"),
        ("aria.tools.files", "list_files"),
        ("aria.tools.files", "search_files"),
    ]
    explicit_schemas = {
        "read_file": ReadFileSchema,
        "write_file": WriteFileSchema,
        "edit_file": EditFileSchema,
        "list_files": ListFilesSchema,
        "search_files": SearchFilesSchema,
    }
    tools: list[FunctionTool] = []
    for mod, fn in tool_specs:
        func = _import_function(mod, fn)
        schema = explicit_schemas.get(fn)
        if schema is not None:
            tools.append(FunctionTool.from_defaults(fn=func, fn_schema=schema))
        else:
            tools.append(FunctionTool.from_defaults(fn=func))
    return tools


def _get_core_tools() -> list[FunctionTool]:
    """Worker core tools: plan, scratchpad, shell."""
    from aria.tools.schemas import PlanSchema, ScratchpadSchema
    from aria.tools.shell.functions import ShellToolSchema

    tool_specs = [
        ("aria.tools.planner", "plan"),
        ("aria.tools.scratchpad", "scratchpad"),
        ("aria.tools.shell", "shell"),
    ]
    explicit_schemas = {
        "plan": PlanSchema,
        "scratchpad": ScratchpadSchema,
        "shell": ShellToolSchema,
    }
    tools: list[FunctionTool] = []
    for mod, fn in tool_specs:
        func = _import_function(mod, fn)
        schema = explicit_schemas.get(fn)
        if schema is not None:
            tools.append(FunctionTool.from_defaults(fn=func, fn_schema=schema))
        else:
            tools.append(FunctionTool.from_defaults(fn=func))
    return tools


def _get_file_tools() -> list[FunctionTool]:
    """Worker file tools: full set including file_info and copy_file."""
    from aria.tools.files.unified_read import (
        FileInfoSchema,
        ListFilesSchema,
        ReadFileSchema,
        SearchFilesSchema,
    )
    from aria.tools.files.write_operations import (
        EditFileSchema,
        WriteFileSchema,
    )
    from aria.tools.schemas import CopyFileSchema

    tool_specs = [
        ("aria.tools.files", "read_file"),
        ("aria.tools.files", "write_file"),
        ("aria.tools.files", "edit_file"),
        ("aria.tools.files", "file_info"),
        ("aria.tools.files", "list_files"),
        ("aria.tools.files", "search_files"),
        ("aria.tools.files", "copy_file"),
    ]
    explicit_schemas = {
        "read_file": ReadFileSchema,
        "write_file": WriteFileSchema,
        "edit_file": EditFileSchema,
        "file_info": FileInfoSchema,
        "list_files": ListFilesSchema,
        "search_files": SearchFilesSchema,
        "copy_file": CopyFileSchema,
    }
    tools: list[FunctionTool] = []
    for mod, fn in tool_specs:
        func = _import_function(mod, fn)
        schema = explicit_schemas.get(fn)
        if schema is not None:
            tools.append(FunctionTool.from_defaults(fn=func, fn_schema=schema))
        else:
            tools.append(FunctionTool.from_defaults(fn=func))
    return tools


def _get_ax_tools() -> list[FunctionTool]:
    """Single unified ax dispatcher tool."""
    from aria.tools.ax import ax
    from aria.tools.ax.dispatcher import AxSchema

    return [FunctionTool.from_defaults(async_fn=ax, fn_schema=AxSchema)]


def _get_worker_ax_tools() -> list[FunctionTool]:
    """Worker-safe ax dispatcher without memory or worker delegation."""
    from aria.tools.ax.worker import WorkerAxSchema, worker_ax

    return [
        FunctionTool.from_defaults(
            async_fn=worker_ax,
            name="ax",
            fn_schema=WorkerAxSchema,
        )
    ]


_CATEGORY_LOADERS: dict[str, Callable[[], list[FunctionTool]]] = {
    CORE_LITE: _get_core_lite_tools,
    FILES_LITE: _get_file_lite_tools,
    CORE: _get_core_tools,
    FILES: _get_file_tools,
    AX: _get_ax_tools,
    WORKER_AX: _get_worker_ax_tools,
}


def get_tools(categories: list[str] | None = None) -> list[FunctionTool]:
    """Get tools by category. None returns all tools.

    When multiple categories are loaded, tools are deduplicated by name
    so the same tool is never registered twice.

    Args:
        categories: List of category names to load.
            None loads all categories.

    Returns:
        List of FunctionTool instances (deduplicated by name).
    """
    if categories is None:
        categories = ALL_CATEGORIES

    tools: list[FunctionTool] = []
    seen: set[str] = set()
    for cat in categories:
        loader = _CATEGORY_LOADERS.get(cat)
        if loader is None:
            logger.warning(f"Unknown tool category: {cat}")
            continue
        try:
            for tool in loader():
                name = tool.metadata.name or ""
                if name not in seen:
                    tools.append(tool)
                    seen.add(name)
        except Exception as exc:
            logger.error(f"Failed to load {cat} tools: {exc}")

    return tools
