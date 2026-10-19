import asyncio
import unittest
from unittest.mock import AsyncMock

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.middleware.path_cors import PathCORSMiddleware


class PathCORSMiddlewareTest(unittest.TestCase):
    def test_policy_uses_configured_path_and_replaces_cache_header(self):
        async def application(scope, receive, send):
            await JSONResponse({"ok": True}, headers={"Cache-Control": "public, max-age=300"})(scope, receive, send)

        client = TestClient(PathCORSMiddleware(
            application, path="/configured-path", enabled=True,
            allowed_origins=["https://preview.example"],
        ))
        result = client.post("/configured-path", headers={"Origin": "https://preview.example"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["access-control-allow-origin"], "https://preview.example")
        self.assertEqual(result.headers.get_list("cache-control"), ["no-store"])
        other = client.get("/other", headers={"Origin": "https://other.example"})
        self.assertEqual(other.headers["cache-control"], "public, max-age=300")
        self.assertEqual(other.headers["access-control-allow-origin"], "*")

    def test_disabled_policy_blocks_every_method_without_calling_application(self):
        application = AsyncMock()
        client = TestClient(PathCORSMiddleware(
            application, path="/configured-path", enabled=False, allowed_origins=(),
        ))
        for method in ("GET", "POST", "OPTIONS", "PUT", "PATCH", "DELETE", "HEAD"):
            with self.subTest(method=method):
                result = client.request(method, "/configured-path")
                self.assertEqual(result.status_code, 404)
                self.assertEqual(result.headers["cache-control"], "no-store")
        application.assert_not_called()

    def test_non_http_scopes_pass_through_without_path_policy(self):
        for scope in ({"type": "lifespan"}, {"type": "websocket", "path": "/configured-path"}):
            with self.subTest(scope=scope):
                application, receive, send = AsyncMock(), AsyncMock(), AsyncMock()
                middleware = PathCORSMiddleware(
                    application, path="/configured-path", enabled=False, allowed_origins=(),
                )
                asyncio.run(middleware(scope, receive, send))
                application.assert_awaited_once_with(scope, receive, send)
