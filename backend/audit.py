"""Append-only audit trail for the Campus Customs agent team.

Every agent-loop step lands in output/audit_trail.json: which agent ran, who delegated to
it, what it said, which MCP tool it called with which arguments, what came back, and what
the step cost in tokens.

The file is a JSON array that is only ever appended to. Runs accumulate, so a later run
never erases the evidence from an earlier one.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

from config import AUDIT_PATH, MODEL_NAME
from models import AuditEntry

_WRITE_LOCK = threading.Lock()

# Tool results can be long. Keep the trail readable but never silently lose that a value
# was returned -- oversized payloads are truncated with a marker.
MAX_RESULT_CHARS = 4000
MAX_TEXT_CHARS = 4000


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"... [truncated, {len(value)} chars total]"
    if isinstance(value, (dict, list)):
        try:
            blob = json.dumps(value)
        except (TypeError, ValueError):
            return str(value)[:limit]
        if len(blob) > limit:
            return blob[:limit] + f"... [truncated, {len(blob)} chars total]"
    return value


def new_run_id() -> str:
    return f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def read_trail(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read the whole trail, or just one run."""
    if not Path(AUDIT_PATH).exists():
        return []
    try:
        entries = json.loads(Path(AUDIT_PATH).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(entries, list):
        return []
    if run_id:
        return [e for e in entries if e.get("run_id") == run_id]
    return entries


def append_entries(entries: Sequence[AuditEntry]) -> None:
    """Append entries to output/audit_trail.json. Never truncates what is already there."""
    if not entries:
        return
    path = Path(AUDIT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    with _WRITE_LOCK:
        existing: List[Dict[str, Any]] = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    existing = loaded
                else:  # someone put something else here; keep it rather than destroy it
                    path.with_suffix(".unreadable.json").write_text(
                        path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
            except (json.JSONDecodeError, OSError):
                path.with_suffix(".unreadable.json").write_text(
                    path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
                )

        existing.extend(e.model_dump() for e in entries)

        # Write to a temp file and swap, so an interrupted write cannot corrupt the trail.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)


class RunRecorder:
    """Records one ticket run. Writes through to the trail as the run progresses."""

    def __init__(self, run_id: str, ticket_id: Optional[int]) -> None:
        self.run_id = run_id
        self.ticket_id = ticket_id
        self._seq = 0
        self._lock = threading.Lock()

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def record(
        self,
        event: str,
        agent: str,
        *,
        summary: str = "",
        depth: int = 0,
        chain: Iterable[str] = (),
        tool_name: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        tool_result: Any = None,
        text: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        model: Optional[str] = MODEL_NAME,
        flush: bool = True,
    ) -> AuditEntry:
        entry = AuditEntry(
            run_id=self.run_id,
            seq=self._next_seq(),
            recorded_at=_now(),
            ticket_id=self.ticket_id,
            agent=agent,
            event=event,  # type: ignore[arg-type]
            depth=depth,
            chain=list(chain),
            model=model,
            summary=summary,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=_truncate(tool_result, MAX_RESULT_CHARS),
            text=_truncate(text, MAX_TEXT_CHARS) if text else None,
            usage=usage,
            error=error,
        )
        if flush:
            append_entries([entry])
        return entry

    def record_agent_messages(
        self,
        agent: str,
        messages: Sequence[Any],
        *,
        depth: int = 0,
        chain: Iterable[str] = (),
        skip_before: int = 0,
    ) -> List[AuditEntry]:
        """Turn one agent run's message history into audit entries.

        Walks what the agent actually did -- each model turn, each MCP tool call, each tool
        result, each retry -- so the trail shows the loop rather than just the final answer.
        """
        entries: List[AuditEntry] = []
        chain = list(chain)

        for message in list(messages)[skip_before:]:
            if isinstance(message, ModelResponse):
                usage = None
                if getattr(message, "usage", None) is not None:
                    u = message.usage
                    usage = {
                        "input_tokens": getattr(u, "input_tokens", None),
                        "output_tokens": getattr(u, "output_tokens", None),
                        "total_tokens": getattr(u, "total_tokens", None),
                        "requests": getattr(u, "requests", None),
                    }
                for part in message.parts:
                    if isinstance(part, TextPart) and part.content.strip():
                        entries.append(
                            self.record(
                                "model_response",
                                agent,
                                summary=part.content.strip()[:160],
                                text=part.content,
                                depth=depth,
                                chain=chain,
                                usage=usage,
                                model=getattr(message, "model_name", MODEL_NAME),
                                flush=False,
                            )
                        )
                    elif isinstance(part, ToolCallPart):
                        args = part.args_as_dict() if hasattr(part, "args_as_dict") else part.args
                        entries.append(
                            self.record(
                                "tool_call",
                                agent,
                                summary=f"calls {part.tool_name}",
                                tool_name=part.tool_name,
                                tool_args=args if isinstance(args, dict) else {"raw": str(args)},
                                depth=depth,
                                chain=chain,
                                usage=usage,
                                model=getattr(message, "model_name", MODEL_NAME),
                                flush=False,
                            )
                        )
                    elif isinstance(part, ThinkingPart):
                        continue  # not logged: reasoning text is not an auditable action
            elif isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, ToolReturnPart):
                        entries.append(
                            self.record(
                                "tool_result",
                                agent,
                                summary=f"{part.tool_name} returned",
                                tool_name=part.tool_name,
                                tool_result=part.content,
                                depth=depth,
                                chain=chain,
                                flush=False,
                            )
                        )
                    elif isinstance(part, RetryPromptPart):
                        entries.append(
                            self.record(
                                "agent_error",
                                agent,
                                summary="tool call retried",
                                tool_name=getattr(part, "tool_name", None),
                                error=str(part.content),
                                depth=depth,
                                chain=chain,
                                flush=False,
                            )
                        )

        append_entries(entries)
        return entries
