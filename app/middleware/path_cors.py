"""Path-specific browser access and availability policy."""
from collections.abc import Mapping, Sequence

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PathCORSMiddleware:
    """Preserve public GET CORS and independently configure selected POST paths.

    Disabled paths return 404 for every HTTP method. All selected paths receive
    no-store, including preflight and availability errors. Non-HTTP scopes pass
    through without applying path policy.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        path: str | None = None,
        enabled: bool = False,
        allowed_origins: Sequence[str] = (),
        policies: Mapping[str, tuple[bool, Sequence[str]]] | None = None,
    ) -> None:
        if policies is None:
            if path is None:
                raise ValueError("A path or policies is required")
            policies = {path: (enabled, allowed_origins)}
        elif path is not None:
            raise ValueError("Specify either path or policies")
        self.public_get_cors = CORSMiddleware(
            app,
            allow_origins=["*"],
            allow_methods=["GET"],
            allow_headers=["Accept", "Content-Type"],
        )
        self.policies = {
            selected_path: (is_enabled, CORSMiddleware(
                app,
                allow_origins=list(origins),
                allow_methods=["POST"],
                allow_headers=["Accept", "Content-Type"],
            ))
            for selected_path, (is_enabled, origins) in policies.items()
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.public_get_cors(scope, receive, send)
        policy = self.policies.get(scope["path"])
        if policy is None:
            return await self.public_get_cors(scope, receive, send)

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value)
                    for key, value in message["headers"]
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        enabled, cors = policy
        if not enabled:
            response = JSONResponse({"detail": "Not Found"}, status_code=404)
            return await response(scope, receive, no_store)
        await cors(scope, receive, no_store)
