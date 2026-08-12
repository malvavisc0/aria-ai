"""Reasoning session class - no global state."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .constants import (
    BIAS_PATTERNS,
    COGNITIVE_MODES,
    COGNITIVE_SCAFFOLDING,
    REASONING_TYPES,
)

if TYPE_CHECKING:
    from .database import ReasoningDatabase


class ReasoningSession:
    """A single reasoning session with structured reasoning artifacts."""

    def __init__(self, session_id: str | None = None, agent_id: str | None = None):
        """Initialize a new reasoning session.

        Args:
            session_id: User-provided session identifier
            agent_id: Agent identifier for multi-agent isolation
        """
        self.id = uuid.uuid4().hex
        self.session_id = session_id
        self.agent_id = agent_id
        self.steps: list[dict] = []
        self.reflections: list[dict] = []
        self.scratchpad: dict[str, dict] = {}
        self.tool_events: list[dict[str, Any]] = []
        self.created_at = datetime.now(UTC).isoformat()
        self.confidence_trajectory: list[float] = []
        self._db: ReasoningDatabase | None = None

    def add_step(
        self,
        reason: str,
        content: str,
        cognitive_mode: str = "analysis",
        reasoning_type: str = "deductive",
        evidence: list[str] | None = None,
        confidence: float = 0.65,
    ) -> dict[str, Any]:
        """
        Add one structured reasoning step.

        Args:
            content (str): The reasoning content
            cognitive_mode (str): One of COGNITIVE_MODES
                (analysis, synthesis, evaluation, etc.)
            reasoning_type (str): One of REASONING_TYPES
                (deductive, inductive, abductive, etc.)
            evidence (str): Optional list of evidence supporting this step
            confidence (str): Confidence level (0.0 to 1.0)

        Returns:
            Dict[str, Any]: JSON-compatible step payload
        """
        if cognitive_mode not in COGNITIVE_MODES:
            cognitive_mode = "analysis"
        if reasoning_type not in REASONING_TYPES:
            reasoning_type = "deductive"

        biases = self._detect_biases(content + " " + " ".join(evidence or []))

        step = {
            "id": len(self.steps) + 1,
            "cognitive_mode": cognitive_mode,
            "reasoning_type": reasoning_type,
            "content": content,
            "confidence": confidence,
            "reason": reason,
            "evidence": evidence or [],
            "biases_detected": biases,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        self.steps.append(step)
        self.confidence_trajectory.append(confidence)

        # Persist to database
        self.persist_step(step)

        # Persist tool event (audit)
        self.persist_tool_event(
            tool_name="add_reasoning_step",
            reason=reason,
            timestamp=step["timestamp"],
            payload={
                "step_id": step["id"],
                "cognitive_mode": cognitive_mode,
                "reasoning_type": reasoning_type,
                "confidence": confidence,
            },
        )

        result: dict[str, Any] = {
            "step_id": step["id"],
            "cognitive_mode": cognitive_mode,
            "reasoning_type": reasoning_type,
            "content": content,
            "confidence": confidence,
            "reason": reason,
            "evidence": step["evidence"],
            "biases_detected": biases,
            "timestamp": step["timestamp"],
        }

        if confidence < 0.7:
            result["scaffolding_hint"] = COGNITIVE_SCAFFOLDING[cognitive_mode]

        return result

    def add_reflection(
        self, reason: str, reflection: str, on_step: int | None = None
    ) -> dict[str, Any]:
        """
        Add meta-cognitive reflection.

        Args:
            reflection (str): The reflection content
            on_step (int): Optional step ID this reflection refers to

        Returns:
            Dict[str, Any]: JSON-compatible reflection payload

        Raises:
            ValueError: If on_step references a non-existent step
        """
        # Validate on_step if provided
        if on_step is not None:
            valid_step_ids = [step["id"] for step in self.steps]
            if on_step not in valid_step_ids:
                raise ValueError(
                    f"Invalid on_step={on_step}. Valid step IDs: {valid_step_ids}"
                )

        entry: dict[str, Any] = {
            "id": len(self.reflections) + 1,
            "content": reflection,
            "step_id": on_step,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.reflections.append(entry)

        # Persist to database
        self.persist_reflection(entry)

        # Persist tool event (audit)
        self.persist_tool_event(
            tool_name="add_reflection",
            reason=reason,
            timestamp=entry["timestamp"],
            payload={"reflection_id": entry["id"], "step_id": on_step},
        )

        return {
            "reflection_id": entry["id"],
            "content": reflection,
            "step_id": on_step,
            "reason": reason,
            "timestamp": entry["timestamp"],
        }

    def evaluate(self, reason: str) -> dict[str, Any]:
        """
        Quick quality assessment of the reasoning chain.

        Returns:
            Dict[str, Any]: JSON-compatible evaluation payload
        """
        n_steps = len(self.steps)
        n_refl = len(self.reflections)
        avg_conf = (
            sum(self.confidence_trajectory) / len(self.confidence_trajectory)
            if self.confidence_trajectory
            else 0
        )

        score = min(10, n_steps + n_refl * 2 + int(avg_conf * 10)) // 3

        recommendations: list[str] = []
        if n_steps < 4:
            recommendations.append("Consider more steps")
        if n_refl == 0:
            recommendations.append("Add at least one reflection")
        if avg_conf < 0.6:
            recommendations.append("Low confidence — gather more evidence?")

        now = datetime.now(UTC).isoformat()
        self.persist_tool_event(
            tool_name="evaluate_reasoning",
            reason=reason,
            timestamp=now,
            payload={"quality_score": score},
        )

        return {
            "quality_score": score,
            "steps_count": n_steps,
            "reflections_count": n_refl,
            "average_confidence": avg_conf,
            "recommendations": recommendations,
            "reason": reason,
            "timestamp": now,
        }

    def summary(self, reason: str) -> dict[str, Any]:
        """
        Current state overview.

        Returns:
            Dict[str, Any]: JSON-compatible summary payload
        """
        avg_conf = (
            sum(self.confidence_trajectory) / len(self.confidence_trajectory)
            if self.confidence_trajectory
            else 0
        )
        now = datetime.now(UTC).isoformat()
        self.persist_tool_event(
            tool_name="get_reasoning_summary",
            reason=reason,
            timestamp=now,
            payload=None,
        )
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "steps_count": len(self.steps),
            "reflections_count": len(self.reflections),
            "scratchpad_items_count": len(self.scratchpad),
            "average_confidence": avg_conf,
            "created_at": self.created_at,
            "last_updated": now,
            "reason": reason,
            "timestamp": now,
        }

    def _detect_biases(self, text: str) -> list[str]:
        """
        Detect potential cognitive biases in text.

        Args:
            text (str): Text to analyze

        Returns:
            List[str]: List of detected bias types
        """
        text = text.lower()
        return [
            bias
            for bias, words in BIAS_PATTERNS.items()
            if any(w in text for w in words)
        ]

    def set_database(self, db: "ReasoningDatabase") -> None:
        """Set database instance for persistence."""
        self._db = db

    def to_dict(self) -> dict:
        """Serialize session to dictionary for storage."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "steps": self.steps,
            "reflections": self.reflections,
            "scratchpad": self.scratchpad,
            "tool_events": self.tool_events,
            "confidence_trajectory": self.confidence_trajectory,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReasoningSession":
        """Deserialize session from dictionary."""
        session = cls(session_id=data.get("session_id"), agent_id=data.get("agent_id"))
        session.id = data["id"]
        session.created_at = data["created_at"]
        session.steps = data.get("steps", [])
        session.reflections = data.get("reflections", [])
        session.scratchpad = data.get("scratchpad", {})
        session.tool_events = data.get("tool_events", [])
        session.confidence_trajectory = data.get("confidence_trajectory", [])
        return session

    def persist_metadata(self) -> None:
        """Persist session metadata to database."""
        if self._db and self.session_id and self.agent_id:
            self._db.save_session_metadata(
                self.id, self.session_id, self.agent_id, self.created_at
            )

    def persist_step(self, step: dict) -> None:
        """Persist a step to database."""
        if self._db:
            self._db.save_step(self.id, step)

    def persist_reflection(self, reflection: dict) -> None:
        """Persist a reflection to database."""
        if self._db:
            self._db.save_reflection(self.id, reflection)

    def persist_tool_event(
        self,
        tool_name: str,
        reason: str,
        timestamp: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist a tool call event to database and local memory."""
        event = {
            "tool_name": tool_name,
            "reason": reason,
            "timestamp": timestamp,
            "payload": payload,
        }
        self.tool_events.append(event)
        if self._db:
            self._db.save_tool_event(
                session_internal_id=self.id,
                tool_name=tool_name,
                reason=reason,
                timestamp=timestamp,
                payload=payload,
            )
