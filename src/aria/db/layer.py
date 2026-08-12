"""SQLite compatibility shim for Chainlit SQLAlchemy data layer.

Chainlit's `SQLAlchemyDataLayer` passes Python `list[str]` directly into SQL
parameters for `tags`, which SQLite cannot bind. This subclass serializes
`tags` (and `metadata`, `generation`, `props`) as JSON strings on write and
deserializes them on read.

Database column names use camelCase to match Chainlit's schema; Python
attributes use snake_case with suffixes for reserved names (e.g. ``metadata_``
for the ``metadata`` column).

Workarounds:
1. Assistant messages are promoted to root level (parentId=NULL) on read in
   ``get_all_user_threads`` (the display path) because Chainlit only shows
   root messages in thread history. ``get_thread`` keeps the raw parent-child
   tree so ``restore_chat_history`` can collect all user/assistant steps.
2. ``get_all_user_threads`` infers ``user_id`` from the Chainlit session
   context when not provided, for multi-user support.
"""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional, Union, cast

import aiofiles
from chainlit import PersistedUser
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.step import StepDict
from chainlit.types import (
    ThreadDict,
)
from chainlit.user import User

if TYPE_CHECKING:
    from chainlit.element import Element, ElementDict

logger = logging.getLogger(__name__)

# Constants
ASSISTANT_MESSAGE_TYPE = "assistant_message"


def _json_dumps_or_none(value: Any) -> str | None:
    """Serialize value to JSON string, returning None for None input."""
    if value is None:
        return None
    return json.dumps(value)


def _json_loads_or(value: Any, default: Any) -> Any:
    """Deserialize JSON string or return default.

    Args:
        value: Value to deserialize (JSON string, already-parsed object, or None)
        default: Default value to return if deserialization fails

    Returns:
        Deserialized object or default value
    """
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            # Log warning for debugging data corruption issues
            logger.warning(
                f"Failed to parse JSON value (returning default): "
                f"{value[:100] if len(value) > 100 else value}... Error: {e}"
            )
            return default
    return value


def _parse_iso_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning(f"Failed to parse timestamp value: {value}")
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)

    return parsed


def _to_local_timestamp_string(value: Any) -> Any:
    """Convert ISO timestamps to local-time ISO strings for Chainlit sidebar bucketing.

    Chainlit's frontend groups threads by constructing `new Date(createdAt)` and then
    zeroing local hours before computing day buckets. When timestamps end with `Z`, the
    bucket is based on the user's local timezone. Some SQLite-returned timestamps near
    midnight UTC are therefore grouped into an unexpected day from the user's point of
    view. Returning an explicit local offset keeps the represented wall-clock day aligned
    with the local grouping logic without mutating persisted database values.
    """
    parsed = _parse_iso_timestamp(value)
    if parsed is None:
        return value

    return parsed.astimezone().isoformat(timespec="microseconds")


def _get_session_user() -> User | None:
    """Return the active Chainlit session user, or None if no session.

    Only ``ChainlitContextException`` (no active session) is swallowed; other
    exceptions propagate. Shared by the user-resolution paths to avoid
    duplicating the context-import + try/except boilerplate.
    """
    from chainlit.context import ChainlitContextException, context

    try:
        return context.session.user
    except ChainlitContextException:
        return None


class SQLiteSQLAlchemyDataLayer(SQLAlchemyDataLayer):
    """Chainlit SQLAlchemy data layer patched for SQLite."""

    def _deserialize_step(self, step: StepDict) -> StepDict:
        """Deserialize JSON fields in a step dict.

        Args:
            step: Step dictionary with potentially JSON-string fields

        Returns:
            Step dictionary with deserialized fields (modified in-place)
        """
        step["tags"] = _json_loads_or(step.get("tags"), default=[])
        step["metadata"] = _json_loads_or(step.get("metadata"), default={})
        step["generation"] = _json_loads_or(step.get("generation"), default={})
        return step

    def _deserialize_element(self, element: dict[str, Any]) -> dict[str, Any]:
        """Deserialize JSON fields in an element dict.

        Args:
            element: Element dictionary with potentially JSON-string fields

        Returns:
            Element dictionary with deserialized fields (modified in-place)
        """
        element["props"] = _json_loads_or(element.get("props"), default={})
        return element

    async def get_current_timestamp(self) -> str:
        """Return the current time in UTC tagged as ``Z``.

        Chainlit's default (:meth:`SQLAlchemyDataLayer.get_current_timestamp`)
        writes naive local time and appends ``Z``, mislabeling it as UTC.
        `_to_local_timestamp_string` then re-interprets it and shifts the value
        into the wrong calendar day. Real UTC keeps the stored wall-clock day
        aligned with the local grouping logic.
        """
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _deserialize_thread(self, thread: dict[str, Any]) -> dict[str, Any]:
        """Deserialize JSON fields in a thread dict.

        Args:
            thread: Thread dictionary with potentially JSON-string fields

        Returns:
            Thread dictionary with deserialized fields (modified in-place)
        """
        thread["tags"] = _json_loads_or(thread.get("tags"), default=[])
        thread["metadata"] = _json_loads_or(thread.get("metadata"), default={})
        thread["createdAt"] = _to_local_timestamp_string(thread.get("createdAt"))

        for step in thread.get("steps") or []:
            self._deserialize_step(cast(StepDict, step))
        for element in thread.get("elements") or []:
            self._deserialize_element(element)

        return thread

    def _promote_assistant_messages(self, steps: list) -> None:
        """Workaround: Promote assistant messages to root level for display.

        Chainlit only displays root-level messages (parentId=NULL) in thread
        history. Messages created inside workflow context get parentId set
        automatically, but we want them visible in thread history.

        This modifies steps in-place.

        Args:
            steps: List of step dictionaries to process
        """
        for step in steps:
            if step.get("type") == ASSISTANT_MESSAGE_TYPE and step.get("parentId"):
                logger.debug(
                    f"Promoting assistant message {step.get('id')} to root level "
                    f"(was child of {step.get('parentId')})"
                )
                step["parentId"] = None

    async def get_thread(self, thread_id: str) -> ThreadDict | None:
        """Return thread data without promoting assistant messages.

        Unlike ``get_all_user_threads`` (sidebar display), this returns the
        raw parent-child tree. Promotion is skipped so the resume path
        (``restore_chat_history``) can collect all user/assistant steps
        regardless of parent, and to avoid mutating the dict Chainlit reuses.
        """
        # Bypass our get_all_user_threads override (which promotes messages).
        user_threads = await SQLAlchemyDataLayer.get_all_user_threads(
            self, user_id=None, thread_id=thread_id
        )
        if not user_threads:
            return None

        thread = cast(dict[str, Any], user_threads[0])
        self._deserialize_thread(thread)
        return cast(ThreadDict, thread)

    async def create_user(self, user: User) -> PersistedUser | None:
        """Override create_user to include display_name in the INSERT.

        Chainlit's base implementation omits display_name from the INSERT
        statement, which violates the NOT NULL constraint on users.display_name.
        We fall back to the identifier when display_name is not provided.

        Uses INSERT OR IGNORE to handle race conditions where concurrent
        requests might attempt to create the same user.

        Args:
            user: Chainlit User object with identifier and optional display_name

        Returns:
            PersistedUser if successful, None otherwise
        """
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"SQLiteSQLAlchemyDataLayer: create_user, "
                f"user_identifier={user.identifier}"
            )

        display_name = getattr(user, "display_name", None) or user.identifier
        metadata_str = json.dumps(user.metadata) if user.metadata else "{}"

        # Check if user exists
        existing_user = await self.get_user(user.identifier)

        if not existing_user:
            user_id = str(_uuid.uuid4())
            created_at = await self.get_current_timestamp()

            # Use INSERT OR IGNORE to handle race condition
            # If another request inserted the same user, this will be ignored
            query = (
                'INSERT OR IGNORE INTO users ("id", "identifier", "display_name", '
                '"createdAt", "metadata") '
                "VALUES (:id, :identifier, :display_name, :createdAt, :metadata)"
            )
            await self.execute_sql(
                query=query,
                parameters={
                    "id": user_id,
                    "identifier": user.identifier,
                    "display_name": display_name,
                    "createdAt": created_at,
                    "metadata": metadata_str,
                },
            )

        # Update metadata only for existing users. display_name is set at
        # creation (INSERT) and intentionally not overwritten here: updating it
        # on every login would clobber renames made via the GUI/CLI
        # (see gui/dialogs/edit_user.py, cli/users.py).
        update_query = (
            'UPDATE users SET "metadata" = :metadata WHERE "identifier" = :identifier'
        )
        await self.execute_sql(
            query=update_query,
            parameters={
                "metadata": metadata_str,
                "identifier": user.identifier,
            },
        )

        return await self.get_user(user.identifier)

    async def update_thread(
        self,
        thread_id: str,
        name: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ):
        """Update thread with SQLite-compatible tags serialization.

        Args:
            thread_id: Thread ID to update
            name: Optional new name
            user_id: Optional user ID
            metadata: Optional metadata dict
            tags: Optional list of tags (will be JSON-serialized for SQLite)
        """
        # Chainlit passes `tags` as Python list; sqlite cannot bind it.
        tags_json = _json_dumps_or_none(tags)
        # Pass tags as Any to bypass type check - we intentionally pass a JSON string
        # for SQLite compatibility, even though the base class expects List[str]
        return await super().update_thread(
            thread_id=thread_id,
            name=name,
            user_id=user_id,
            metadata=metadata,
            tags=cast(Any, tags_json),
        )

    async def _resolve_user_for_element(self, thread_id: str) -> str:
        """Resolve user_id from Chainlit session; fall back to DB lookup.

        Only ``ChainlitContextException`` (no active session) is caught when
        reading the session. ``JSONDecodeError`` from a corrupt
        ``users.metadata`` row in :meth:`get_user` is also tolerated (a single
        corrupt row must not 500 every element upload for that user); it falls
        through to the thread-based lookup and ultimately the ``"unknown"``
        fallback. Other genuine exceptions still propagate.
        """
        session_user = _get_session_user()

        if session_user is not None:
            try:
                persisted = await self.get_user(session_user.identifier)
            except json.JSONDecodeError:
                logger.warning(
                    f"Corrupt metadata for user {session_user.identifier}; "
                    "falling back to thread lookup for element upload"
                )
                persisted = None
            if persisted:
                return persisted.id

        user_id = await self._get_user_id_by_thread(thread_id)
        if user_id:
            return user_id

        logger.warning(
            f"Could not resolve user for element in thread {thread_id}; "
            "storing under 'unknown'"
        )
        return "unknown"

    async def _read_element_content(self, element) -> Optional[Union[bytes, str]]:
        """Read bytes to upload, or None to skip upload.

        URL-backed elements return None: the remote URL is kept as the
        persistent source and is *not* mirrored (the element dies if the link
        rots). Path/content elements are read and uploaded.
        """
        if element.path:
            async with aiofiles.open(element.path, "rb") as f:
                return await f.read()
        if element.url:
            return None
        if element.content:
            return element.content
        logger.warning(f"create_element: no content {element.id}")
        return None

    async def _upload_element_content(
        self, element, user_id: str, content: Union[bytes, str]
    ) -> None:
        if not self.storage_provider:
            return
        file_key = f"{user_id}/{element.id}" + (
            f"/{element.name}" if element.name else ""
        )
        if not element.mime:
            element.mime = "application/octet-stream"
        uploaded = await self.storage_provider.upload_file(
            object_key=file_key,
            data=content,
            mime=element.mime,
            overwrite=True,
        )
        if not uploaded:
            raise ValueError(
                "create_element: storage provider upload returned no result"
            )
        # ``object_key`` is the snake_case field ``Element.to_dict()`` reads
        # for ``objectKey``. Setting the camelCase attribute (as the parent
        # does) is silently lost, leaving the row's objectKey NULL and leaking
        # the stored file on thread/element deletion.
        element.url = uploaded.get("url")
        element.object_key = uploaded.get("object_key")

    def _element_insert_query(self, element) -> tuple[str, dict[str, Any]]:
        element_dict = cast(dict[str, Any], element.to_dict())
        element_dict_cleaned = {k: v for k, v in element_dict.items() if v is not None}
        if "props" in element_dict_cleaned:
            element_dict_cleaned["props"] = json.dumps(element_dict_cleaned["props"])
        columns = ", ".join(f'"{c}"' for c in element_dict_cleaned)
        placeholders = ", ".join(f":{c}" for c in element_dict_cleaned)
        updates = ", ".join(f'"{c}" = :{c}' for c in element_dict_cleaned if c != "id")
        query = (
            f"INSERT INTO elements ({columns}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates};"
        )
        return query, element_dict_cleaned

    async def create_element(self, element: "Element"):
        """Override to fix race condition: resolve userId from session context.

        Chainlit's create_element() calls _get_user_id_by_thread() which
        queries the thread's userId column. But create_element runs as a
        fire-and-forget task BEFORE update_thread sets the userId, causing
        the lookup to return None and fall back to "unknown". This results
        in files being stored under storage/unknown/ instead of the user's
        actual directory.

        By resolving the userId from the Chainlit session context (which is
        always available at message time), we avoid the race condition.
        """
        if not self.storage_provider:
            return
        if not element.for_id:
            return

        user_id = await self._resolve_user_for_element(element.thread_id)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"create_element: element_id={element.id}, "
                f"user_id={user_id}, name={element.name}"
            )

        content = await self._read_element_content(element)

        if content is not None:
            await self._upload_element_content(element, user_id, content)

        query, params = self._element_insert_query(element)
        await self.execute_sql(query=query, parameters=params)

    async def create_step(self, step_dict: StepDict):
        """Create/update a step, ensuring SQLite-safe serialization.

        Args:
            step_dict: Step dictionary with potentially list-type tags
        """
        # Chainlit does not json.dumps(tags) for steps, but for SQLite we store
        # tags as TEXT containing a JSON array.
        patched: dict[str, Any] = dict(step_dict)
        if isinstance(patched.get("tags"), list):
            patched["tags"] = _json_dumps_or_none(patched["tags"])

        return await super().create_step(cast(StepDict, patched))

    async def _resolve_user_id_from_context(self) -> str | None:
        """Try to resolve the user_id from the active Chainlit session.

        Returns None when there is no active session or the session user has no
        usable identifier. Database errors are swallowed by the base
        ``execute_sql`` (it returns ``None``), so a DB failure yields ``None``
        rather than raising.
        """
        current_user = _get_session_user()

        identifier = getattr(current_user, "identifier", None)
        if not current_user or not identifier:
            return None

        result = await self.execute_sql(
            query="SELECT id FROM users WHERE identifier = :identifier LIMIT 1",
            parameters={"identifier": identifier},
        )
        if isinstance(result, list) and len(result) > 0:
            user_id = result[0].get("id")
            logger.debug(
                f"Retrieved user_id '{user_id}' from session context "
                f"for user '{identifier}'"
            )
            return user_id
        return None

    async def get_all_user_threads(
        self, user_id: str | None = None, thread_id: str | None = None
    ):
        """Get all threads for a user with proper JSON deserialization.

        Args:
            user_id: Optional user ID (if None, attempts to infer from context)
            thread_id: Optional specific thread ID

        Returns:
            List of thread dictionaries with deserialized JSON fields
        """
        # Fix for multi-user support: If user_id is not provided, try to get it
        # from the current Chainlit session context. This ensures each user
        # only sees their own threads.
        if user_id is None and thread_id is None:
            user_id = await self._resolve_user_id_from_context()

        threads = await super().get_all_user_threads(
            user_id=user_id, thread_id=thread_id
        )
        if threads is None:
            return None

        logger.debug(f"get_all_user_threads returning {len(threads)} thread(s)")

        # Deserialize JSON-string columns into the shapes Chainlit's types expect.
        for t in threads:
            logger.debug(f"Thread {t.get('id')}: {len(t.get('steps', []))} steps")
            self._deserialize_thread(cast(dict[str, Any], t))

            # Promote assistant messages to root level for thread display
            steps = t.get("steps") or []
            self._promote_assistant_messages(steps)

        return threads

    async def get_step(self, step_id: str):
        """Get a step by ID, ensuring JSON fields are deserialized.

        Args:
            step_id: The step ID to retrieve

        Returns:
            StepDict with deserialized JSON fields, or None if not found
        """
        step = await super().get_step(step_id)
        if step is None:
            return None

        return self._deserialize_step(step)

    async def get_element(self, thread_id: str, element_id: str) -> ElementDict | None:
        """Get an element by ID, deserializing ``props`` defensively.

        The parent does ``json.loads(row.get("props", "{}"))``; the default
        only applies when the key is absent, so a NULL ``props`` column (the
        norm for image/pdf/audio/file elements) yields ``json.loads(None)``
        and a TypeError. Deserializing via ``_deserialize_element`` matches the
        other read paths.
        """
        from chainlit.element import ElementDict

        query = (
            'SELECT * FROM elements WHERE "threadId" = :thread_id '
            'AND "id" = :element_id'
        )
        parameters = {"thread_id": thread_id, "element_id": element_id}
        element = await self.execute_sql(query=query, parameters=parameters)
        if not (isinstance(element, list) and element):
            return None

        element_dict = element[0]
        self._deserialize_element(element_dict)
        return ElementDict(
            id=element_dict["id"],
            threadId=element_dict.get("threadId"),
            type=element_dict["type"],
            chainlitKey=element_dict.get("chainlitKey"),
            url=element_dict.get("url"),
            objectKey=element_dict.get("objectKey"),
            name=element_dict["name"],
            props=element_dict.get("props", {}),
            display=element_dict["display"],
            size=element_dict.get("size"),
            language=element_dict.get("language"),
            page=element_dict.get("page"),
            autoPlay=element_dict.get("autoPlay"),
            playerConfig=element_dict.get("playerConfig"),
            forId=element_dict.get("forId"),
            mime=element_dict.get("mime"),
        )

    async def get_favorite_steps(self, user_id: str) -> list[StepDict]:
        """Favorite steps with ``tags``/``generation`` deserialized.

        The parent returns ``tags``/``generation`` as raw JSON strings while
        other read paths return Python objects; ``_deserialize_step`` is
        idempotent for the already-deserialized ``metadata``.
        """
        steps = await super().get_favorite_steps(user_id)
        for step in steps:
            self._deserialize_step(step)
        return steps
