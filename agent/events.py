"""Public streaming events; no model reasoning or raw tool payloads."""
from langgraph.config import get_stream_writer


def emit_event(event: dict) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # Nodes are also called directly by unit tests and standalone utilities.
        return
    writer(event)
