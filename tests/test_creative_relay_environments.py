import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.creative_relay import (
    BETA_PATH, PATH, RelaySettings, forward, load_relay_settings, router,
)
from app.middleware.path_cors import PathCORSMiddleware

ORIGIN = "https://template.me-pppmp.com"
PRODUCTION = RelaySettings("10.140.0.10", "cms-api.me-pppmp.com", (ORIGIN,))
BETA = RelaySettings("10.140.0.27", "beta-cms-api.me-pppmp.com", (ORIGIN,))
PAYLOAD = {"url": "https://creative.example/item", "role": "it8"}


class RelayEnvironmentTest(unittest.TestCase):
    def client(self, primary=PRODUCTION, beta=BETA):
        app = FastAPI()
        app.state.creative_relay_settings = primary
        app.state.creative_relay_beta_settings = beta
        app.add_middleware(PathCORSMiddleware, policies={
            path: (settings is not None, settings.origins if settings else ())
            for path, settings in ((PATH, primary), (BETA_PATH, beta))
        })
        app.include_router(router)
        @app.get("/health")
        def health():
            return {"ok": True}
        return TestClient(app)

    @patch("app.api.creative_relay.forward", return_value={"ok": True})
    def test_each_endpoint_uses_its_own_destination(self, send):
        client = self.client()
        for path, expected in ((PATH, PRODUCTION), (BETA_PATH, BETA)):
            with self.subTest(path=path):
                result = client.post(path, json=PAYLOAD)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.headers["cache-control"], "no-store")
                self.assertEqual(send.call_args.args, (expected, PAYLOAD))

    def test_preflight_for_both_paths_and_legacy_get(self):
        client = self.client()
        for path in (PATH, BETA_PATH):
            for origin, expected_status in ((ORIGIN, 200), ("https://other.example", 400)):
                result = client.options(path, headers={
                    "Origin": origin, "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                })
                self.assertEqual(result.status_code, expected_status)
                self.assertEqual(result.headers["cache-control"], "no-store")
                if expected_status == 200:
                    self.assertEqual(result.headers["access-control-allow-origin"], ORIGIN)
                else:
                    self.assertNotIn("access-control-allow-origin", result.headers)
        result = client.get("/health", headers={"Origin": "https://other.example"})
        self.assertEqual(result.headers["access-control-allow-origin"], "*")

    @patch("app.api.creative_relay.forward", return_value={"ok": True})
    def test_missing_beta_never_falls_back_to_production(self, send):
        client = self.client(beta=None)
        for method in ("POST", "OPTIONS", "GET"):
            result = client.request(method, BETA_PATH)
            self.assertEqual(result.status_code, 404)
            self.assertEqual(result.headers["cache-control"], "no-store")
        send.assert_not_called()
        self.assertEqual(client.post(PATH, json=PAYLOAD).status_code, 200)
        self.assertEqual(send.call_args.args[0], PRODUCTION)

    @patch("app.api.creative_relay.forward")
    def test_disabled_blocks_both_paths(self, send):
        client = self.client(primary=None, beta=None)
        for path in (PATH, BETA_PATH):
            result = client.post(path, json=PAYLOAD)
            self.assertEqual(result.status_code, 404)
            self.assertEqual(result.headers["cache-control"], "no-store")
        send.assert_not_called()

    def test_settings_are_independent_and_partial_beta_fails(self):
        env = {
            "CREATIVE_RELAY_ENABLED": "true",
            "CREATIVE_RELAY_PRIVATE_IP": PRODUCTION.private_ip,
            "CREATIVE_RELAY_HOSTNAME": PRODUCTION.hostname,
            "CREATIVE_RELAY_BETA_PRIVATE_IP": BETA.private_ip,
            "CREATIVE_RELAY_BETA_HOSTNAME": BETA.hostname,
            "CREATIVE_RELAY_ALLOWED_ORIGINS": ORIGIN,
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_relay_settings(), PRODUCTION)
            self.assertEqual(load_relay_settings("beta"), BETA)
        for missing in ("CREATIVE_RELAY_BETA_PRIVATE_IP", "CREATIVE_RELAY_BETA_HOSTNAME"):
            with patch.dict(os.environ, {k: v for k, v in env.items() if k != missing}, clear=True):
                with self.assertRaises(ValueError):
                    load_relay_settings("beta")
        without_beta = {k: v for k, v in env.items() if not k.startswith("CREATIVE_RELAY_BETA_")}
        with patch.dict(os.environ, without_beta, clear=True):
            self.assertIsNone(load_relay_settings("beta"))
            self.assertEqual(load_relay_settings(), PRODUCTION)
        with patch.dict(os.environ, {**env, "CREATIVE_RELAY_ENABLED": "false"}, clear=True):
            self.assertIsNone(load_relay_settings())
            self.assertIsNone(load_relay_settings("beta"))
        for key, value in (("CREATIVE_RELAY_BETA_PRIVATE_IP", "8.8.8.8"),
                           ("CREATIVE_RELAY_BETA_HOSTNAME", "https://bad.example/path")):
            with patch.dict(os.environ, {**env, key: value}, clear=True):
                with self.assertRaises(ValueError):
                    load_relay_settings("beta")

    @patch("app.api.creative_relay.PrivateHTTPSConnection")
    def test_beta_still_calls_original_cms_path(self, connection):
        upstream = connection.return_value.getresponse.return_value
        upstream.status = 200
        upstream.getheader.return_value = "application/json"
        upstream.read.return_value = b'{"code":200,"data":{}}'
        self.assertEqual(forward(BETA, PAYLOAD).status_code, 200)
        connection.assert_called_once_with(BETA)
        args, kwargs = connection.return_value.request.call_args
        self.assertEqual(args, ("POST", PATH))
        self.assertEqual(kwargs["headers"]["Host"], BETA.hostname)
