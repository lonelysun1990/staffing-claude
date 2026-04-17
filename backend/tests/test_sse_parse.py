import asyncio
import json

from evals.sse_parse import parse_sse_stream


async def _fake_stream(chunks: list[str]):
    for c in chunks:
        yield c


def test_parse_sse_two_events():
    payload1 = {"type": "text_delta", "delta": "hi", "trace_id": "t1"}
    payload2 = {"type": "done", "session_id": 1, "trace_id": "t1"}
    raw = (
        f"data: {json.dumps(payload1)}\n\n"
        f"data: {json.dumps(payload2)}\n\n"
    )

    async def run():
        ev = await parse_sse_stream(_fake_stream([raw]))
        return ev

    events = asyncio.run(run())
    assert len(events) == 2
    assert events[0]["type"] == "text_delta"
    assert events[1]["type"] == "done"
