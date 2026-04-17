"""Parse SSE lines emitted by run_agent_stream (data: {...}\\n\\n)."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, List


async def parse_sse_stream(
    stream: AsyncGenerator[str, None],
) -> List[dict[str, Any]]:
    """Consume async string chunks and return parsed JSON event dicts."""
    buffer = ""
    events: List[dict[str, Any]] = []
    async for chunk in stream:
        buffer += chunk
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            for line in raw.split("\n"):
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
    # Trailing incomplete event without \n\n is ignored (stream should end with done/error)
    return events
