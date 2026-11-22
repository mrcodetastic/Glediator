from __future__ import annotations

from urllib.parse import urlsplit

from glediator.output.websocket_output import OutputStatus, WebSocketOutput


class MrCodetasticWebSocketOutput(WebSocketOutput):
    """Compatibility wrapper accepting a ws://host:port URL."""

    def __init__(self, url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 12345
        super().__init__(host=host, port=port)


__all__ = ["MrCodetasticWebSocketOutput", "OutputStatus", "WebSocketOutput"]
