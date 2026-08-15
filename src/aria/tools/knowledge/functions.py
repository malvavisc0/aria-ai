"""Knowledge hub management functions (ax family 'knowledge')."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from aria.config.api import KnowledgeHub
from aria.tools import Reason, err, ok
from aria.tools.decorators import log_tool_call
from aria.tools.knowledge.models import KnowledgeIndexStateModel

_TOOL = "knowledge"


def _index_status() -> dict[str, Any]:
    """Read indexed-file count, skipped files, and last index time from state."""
    from aria.tools.database import get_tools_database

    with get_tools_database().get_session() as session:
        indexed_count = session.execute(
            select(func.count())
            .select_from(KnowledgeIndexStateModel)
            .where(KnowledgeIndexStateModel.state == "indexed")
        ).scalar_one()
        skipped_rows = (
            session.execute(
                select(KnowledgeIndexStateModel).where(
                    KnowledgeIndexStateModel.state == "skipped"
                )
            )
            .scalars()
            .all()
        )
        last_at = session.execute(
            select(func.max(KnowledgeIndexStateModel.indexed_at))
        ).scalar_one()
    skipped = [
        {"path": r.path, "reason": r.skip_reason, "size": r.size} for r in skipped_rows
    ]
    return {
        "indexed_files": indexed_count,
        "skipped": skipped,
        "last_index_at": last_at.isoformat() if last_at is not None else None,
    }


@log_tool_call
async def knowledge_status(reason: Reason) -> str:
    """Show knowledge hub index status."""
    from aria.scripts.docling import is_installed
    from aria.server.digest_lease import active_digest

    data: dict[str, Any] = {
        "enabled": KnowledgeHub.enabled,
        "dir": KnowledgeHub.dir,
        "collection": "aria_knowledge",
        "docling_installed": is_installed(),
        "digesting": active_digest() is not None,
    }
    data.update(_index_status())
    return ok(tool=_TOOL, reason=reason, data=data)


@log_tool_call
async def knowledge_reindex(reason: Reason, force: bool = False) -> str:
    """Trigger a re-index of the knowledge hub documents directory."""
    from aria.server.knowledge_hub import KnowledgeHubIndexer

    if not KnowledgeHub.enabled:
        return err(
            tool=_TOOL,
            reason=reason,
            code="hub_disabled",
            message="Knowledge hub is disabled",
        )
    result = await KnowledgeHubIndexer().reindex(force=force)
    return ok(tool=_TOOL, reason=reason, data=result)
