import json
import os
import socket
import ssl
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.creative_relay import (
    MAX_REQUEST, MAX_RESPONSE, PATH,
    PrivateHTTPSConnection, RelaySettings, forward, load_relay_settings, router,
)

from app.middleware.path_cors import PathCORSMiddleware

SETTINGS = RelaySettings("10.140.0.27", "beta-cms-api.me-pppmp.com", ("https://preview.example",))
PAYLOAD = {"url": "https://creative.example/item", "role": "it8"}


class RelayTest(unittest.TestCase):
    def client(self, settings=SETTINGS):
        app = FastAPI()
        app.state.creative_relay_settings = settings
        app.add_middleware(
            PathCORSMiddleware, path=PATH, enabled=settings is not None,
            allowed_origins=settings.origins if settings is not None else (),
        )
        app.include_router(router)
        @app.get("/health")
        def health():
            return {"status": "ok"}
        return TestClient(app)

    @patch("app.api.creative_relay.PrivateHTTPSConnection")
    def test_preserves_json_status_and_only_fixed_headers(self, connection):
        for status in (200, 404, 409, 422, 429, 503):
            with self.subTest(status=status):
                response = connection.return_value.getresponse.return_value
                response.status = status
                response.getheader.return_value = "application/json; charset=utf-8"
                response.read.return_value = b'{"code":409,"message":"result","data":null}'
                result = self.client().post(PATH, json=PAYLOAD, headers={
                    "Cookie": "secret", "Authorization": "secret", "X-Forwarded-For": "1.2.3.4",
                })
                self.assertEqual(result.status_code, status)
                self.assertEqual(result.json()["message"], "result")
                self.assertEqual(result.headers["cache-control"], "no-store")
                args, kwargs = connection.return_value.request.call_args
                self.assertEqual(args, ("POST", PATH))
                self.assertEqual(set(kwargs["headers"]), {"Host", "Accept", "Content-Type"})
                self.assertEqual(kwargs["headers"]["Host"], SETTINGS.hostname)
                self.assertEqual(json.loads(kwargs["body"]), PAYLOAD)
                connection.return_value.close.assert_called()

    @patch("app.api.creative_relay.PrivateHTTPSConnection")
    def test_rejects_redirect_html_invalid_and_oversized_responses(self, connection):
        response = connection.return_value.getresponse.return_value
        for status, kind, body in (
            (302, "application/json", b'{}'),
            (200, "text/html", b'<html>error</html>'),
            (200, "application/json", b'bad json'),
            (200, "application/json", b'[]'),
            (200, "application/json", b'x' * (MAX_RESPONSE + 1)),
        ):
            response.status, response.getheader.return_value, response.read.return_value = status, kind, body
            connection.return_value.request.reset_mock()
            self.assertEqual(self.client().post(PATH, json=PAYLOAD).status_code, 502)
            connection.return_value.request.assert_called_once()

    @patch("app.api.creative_relay.PrivateHTTPSConnection")
    def test_network_errors_and_timeout(self, connection):
        for error, expected in ((socket.timeout(), 504), (ssl.SSLError(), 502), (OSError(), 502)):
            connection.return_value.request.side_effect = error
            result = self.client().post(PATH, json=PAYLOAD)
            self.assertEqual(result.status_code, expected)
            self.assertEqual(result.headers["cache-control"], "no-store")

    @patch("app.api.creative_relay.forward")
    def test_invalid_inputs_do_not_reach_upstream(self, send):
        for data in ({}, {"url": "file:///etc/passwd"}, {**PAYLOAD, "role": "sales"},
                     {**PAYLOAD, "upstream": "https://evil.example"}, {"url": 123},
                     {**PAYLOAD, "url": "https://creative.example/\nsecret"}):
            result = self.client().post(PATH, json=data)
            self.assertEqual(result.status_code, 422)
            self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(self.client().post(PATH, content=b'x' * (MAX_REQUEST + 1), headers={"Content-Type": "application/json"}).status_code, 413)
        self.assertEqual(self.client().post(PATH, content=b'{}').status_code, 415)
        send.assert_not_called()

    @patch("app.api.creative_relay.forward")
    def test_missing_role_and_null_are_sales(self, send):
        send.return_value = {"ok": True}
        for payload in ({"url": PAYLOAD["url"]}, {"url": PAYLOAD["url"], "role": None}):
            self.assertEqual(self.client().post(PATH, json=payload).status_code, 200)
            self.assertIsNone(send.call_args.args[1]["role"])

    def test_cors_is_scoped_and_all_responses_are_uncacheable(self):
        client = self.client()
        headers = {"Origin": SETTINGS.origins[0], "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
        response = client.options(PATH, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], SETTINGS.origins[0])
        self.assertEqual(response.headers["cache-control"], "no-store")
        headers["Origin"] = "https://evil.example"
        response = client.options(PATH, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertEqual(client.options("/health", headers=headers).status_code, 400)
        self.assertEqual(client.get("/health", headers={"Origin": "https://evil.example"}).headers["access-control-allow-origin"], "*")
        self.assertEqual(client.get(PATH).status_code, 405)

    @patch("app.api.creative_relay.forward")
    def test_disabled_is_unavailable(self, send):
        for method in ("post", "options", "get"):
            result = getattr(self.client(None), method)(PATH)
            self.assertEqual(result.status_code, 404)
            self.assertEqual(result.headers["cache-control"], "no-store")
        send.assert_not_called()

    def test_settings_fail_closed(self):
        valid = {"CREATIVE_RELAY_ENABLED": "true", "CREATIVE_RELAY_PRIVATE_IP": SETTINGS.private_ip,
                 "CREATIVE_RELAY_HOSTNAME": SETTINGS.hostname,
                 "CREATIVE_RELAY_ALLOWED_ORIGINS": SETTINGS.origins[0]}
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(load_relay_settings())
        with patch.dict(os.environ, valid, clear=True):
            self.assertEqual(load_relay_settings(), SETTINGS)
        for key, value in (("CREATIVE_RELAY_PRIVATE_IP", "8.8.8.8"), ("CREATIVE_RELAY_PRIVATE_IP", "127.0.0.1"),
                           ("CREATIVE_RELAY_HOSTNAME", "https://evil.example/path"), ("CREATIVE_RELAY_ALLOWED_ORIGINS", "*")):
            with patch.dict(os.environ, {**valid, key: value}, clear=True):
                with self.assertRaises(ValueError):
                    load_relay_settings()

    @patch("app.api.creative_relay.ssl.create_default_context")
    @patch("app.api.creative_relay.socket.create_connection")
    def test_private_tcp_destination_retains_hostname_tls(self, tcp, context):
        connection = PrivateHTTPSConnection(SETTINGS)
        connection.connect()
        tcp.assert_called_once_with((SETTINGS.private_ip, 443), 5)
        context.return_value.wrap_socket.assert_called_once_with(tcp.return_value, server_hostname=SETTINGS.hostname)
        context.return_value.wrap_socket.return_value.settimeout.assert_called_once_with(10)


if __name__ == "__main__":
    unittest.main()
