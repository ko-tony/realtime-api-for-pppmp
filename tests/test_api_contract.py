import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import get_db
from main import app

SAMPLE_ROW = SimpleNamespace(
    cityName="臺北市",
    aqi=42,
    pm25=Decimal("12.5"),
    o3=Decimal("30"),
    aqiDate=datetime(2026, 9, 3, 15, 0, tzinfo=timezone(timedelta(hours=8))),
    airTemperature=28.5,
    maxTemperature=32.1,
    minTemperature=24.3,
    humidity=70,
    uvIndex=6,
    weather="晴",
    weatherDate=datetime(2026, 9, 3, 12, 0, tzinfo=timezone(timedelta(hours=8))),
)


class ApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.dependency_overrides[get_db] = lambda: object()
        cls.client = TestClient(app)
        cls.paths = cls.client.get("/openapi.json").json()["paths"]

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()

    def test_public_data_paths(self) -> None:
        data_paths = [path for path in self.paths if path.startswith("/api/")]

        self.assertEqual(data_paths, ["/api/v1/environment", "/api/v1/finance"])

    def test_removed_features_are_not_exposed(self) -> None:
        for path in (
            "/cwa_uv_live",
            "/moenv_live",
            "/env_live_1",
            "/api/v1/cwa-uv-live",
            "/api/v1/air-quality",
            "/register",
            "/token",
            "/excel_to_word",
            "/items/",
            "/weather",
            "/api/v1/weather",
        ):
            with self.subTest(path=path):
                self.assertNotIn(path, self.paths)

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @patch("app.services.environment.repository.list_environment")
    def test_environment_returns_merged_air_quality_and_weather(
        self, list_environment
    ) -> None:
        list_environment.return_value = [SAMPLE_ROW]

        response = self.client.get("/api/v1/environment")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "cityName": "臺北市",
                    "aqi": 42,
                    "pm25": 12.5,
                    "o3": 30.0,
                    "aqiDate": "2026-09-03T15:00:00+08:00",
                    "airTemperature": 28.5,
                    "maxTemperature": 32.1,
                    "minTemperature": 24.3,
                    "humidity": 70,
                    "uvIndex": 6,
                    "weather": "晴",
                    "weatherDate": "2026-09-03T12:00:00+08:00",
                }
            ],
        )
        self.assertIn("s-maxage=300", response.headers["cache-control"])

    @patch("app.services.environment.repository.list_environment")
    def test_empty_result_returns_not_found(self, list_environment) -> None:
        list_environment.return_value = []

        response = self.client.get("/api/v1/environment")

        self.assertEqual(response.status_code, 404)

    @patch("app.services.environment.repository.list_environment")
    def test_database_errors_return_service_unavailable(
        self, list_environment
    ) -> None:
        list_environment.side_effect = SQLAlchemyError("unavailable")

        with self.assertLogs("app.services.environment", level="ERROR"):
            response = self.client.get("/api/v1/environment")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "Data source is temporarily unavailable"}
        )

    def test_public_cors_does_not_allow_credentials(self) -> None:
        response = self.client.get(
            "/health", headers={"Origin": "https://publisher.example"}
        )

        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", response.headers)


if __name__ == "__main__":
    unittest.main()
