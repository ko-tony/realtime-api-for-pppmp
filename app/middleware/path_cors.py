"""Path-specific browser access and availability policy."""
from collections.abc import Sequence

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PathCORSMiddleware:
    """Keep public GET CORS for other paths and apply a selected path's policy.

    The selected path permits POST CORS from configured origins when enabled;
    when disabled it returns 404 for every HTTP method. All HTTP responses on
    that path receive no-store, including preflight and availability errors.
    Non-HTTP scopes pass through without applying path policy.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        path: str,
        enabled: bool,
        allowed_origins: Sequence[str],
    ) -> None:
        self.path = path
        self.enabled = enabled
        self.public_get_cors = CORSMiddleware(
            app,
            allow_origins=["*"],
            allow_methods=["GET"],
            allow_headers=["Accept", "Content-Type"],
        )
        self.path_post_cors = CORSMiddleware(
            app,
            allow_origins=list(allowed_origins),
            allow_methods=["POST"],
            allow_headers=["Accept", "Content-Type"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != self.path:
            return await self.public_get_cors(scope, receive, send)

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value)
                    for key, value in message["headers"]
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        if not self.enabled:
            response = JSONResponse({"detail": "Not Found"}, status_code=404)
            return await response(scope, receive, no_store)
        await self.path_post_cors(scope, receive, no_store)
