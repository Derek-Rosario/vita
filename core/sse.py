import asyncio
import json

from asgiref.sync import async_to_sync
from channels.generic.http import AsyncHttpConsumer
from channels.layers import get_channel_layer

_SSE_GROUP = "sse_events"


class SSEConsumer(AsyncHttpConsumer):
    async def __call__(self, scope, receive, send):
        # Save the ASGI receive callable so handle() can monitor for disconnects.
        self._http_receive = receive
        await super().__call__(scope, receive, send)

    async def handle(self, body):
        channel_layer = get_channel_layer()
        await channel_layer.group_add(_SSE_GROUP, self.channel_name)
        await self.send_headers(
            headers=[
                (b"Cache-Control", b"no-cache"),
                (b"Content-Type", b"text/event-stream"),
                (b"Transfer-Encoding", b"chunked"),
                (b"X-Accel-Buffering", b"no"),
            ]
        )
        try:
            await self._sse_loop(channel_layer)
        finally:
            await channel_layer.group_discard(_SSE_GROUP, self.channel_name)

    async def _sse_loop(self, channel_layer):
        disconnect_task = asyncio.create_task(self._await_disconnect())
        try:
            while True:
                channel_task = asyncio.create_task(
                    channel_layer.receive(self.channel_name)
                )
                done, _ = await asyncio.wait(
                    {channel_task, disconnect_task},
                    timeout=15.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if disconnect_task in done:
                    channel_task.cancel()
                    return

                if channel_task in done:
                    msg = channel_task.result()
                    event_type = msg.get("event_type", "message")
                    data = msg.get("data", "")
                    # SSE requires every line of multi-line data to be prefixed
                    # with "data: " — a single prefix only covers the first line.
                    data_lines = "\n".join(
                        f"data: {line}" for line in (data.splitlines() or [""])
                    )
                    try:
                        await self.send_body(
                            f"event: {event_type}\n{data_lines}\n\n".encode(),
                            more_body=True,
                        )
                    except Exception:
                        return
                else:
                    # Timeout: send keepalive comment to keep connection alive.
                    channel_task.cancel()
                    try:
                        await self.send_body(b": keepalive\n\n", more_body=True)
                    except Exception:
                        return
        finally:
            disconnect_task.cancel()
            try:
                await disconnect_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _await_disconnect(self):
        """Read from the ASGI receive queue until the client disconnects."""
        while True:
            msg = await self._http_receive()
            if msg["type"] == "http.disconnect":
                return


def send_event(channel, event_type, data, json_encode=True):
    """Send an SSE event to all connected clients.

    Drop-in replacement for django_eventstream.send_event.
    The `channel` argument is accepted for compatibility but ignored.
    """
    data_str = json.dumps(data) if json_encode else data
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        _SSE_GROUP,
        {
            "type": "sse.message",
            "event_type": event_type,
            "data": data_str,
        },
    )
