"""A fixed-destination relay; it never fetches the submitted creative URL."""
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

PATH = "/api/v1/creative/view"
MAX_REQUEST = 16 * 1024
MAX_RESPONSE = 256 * 1024
router = APIRouter()


@dataclass(frozen=True)
class RelaySettings:
    private_ip: str
    hostname: str
    origins: tuple[str, ...]


def load_relay_settings() -> RelaySettings | None:
    if os.getenv("CREATIVE_RELAY_ENABLED", "false").lower() != "true":
        return None
    ip = os.environ.get("CREATIVE_RELAY_PRIVATE_IP", "")
    address = ipaddress.IPv4Address(ip)
    if not any(address in ipaddress.ip_network(net) for net in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
    )):
        raise ValueError("CREATIVE_RELAY_PRIVATE_IP must be an RFC1918 IPv4 address")
    hostname = os.environ.get("CREATIVE_RELAY_HOSTNAME", "")
    if len(hostname) > 253 or not re.fullmatch(
        r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
        r"[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", hostname
    ):
        raise ValueError("CREATIVE_RELAY_HOSTNAME must be a bare DNS hostname")
    origins = tuple(x.strip() for x in os.getenv("CREATIVE_RELAY_ALLOWED_ORIGINS", "").split(",") if x.strip())
    if not origins or any(not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?", x) for x in origins):
        raise ValueError("CREATIVE_RELAY_ALLOWED_ORIGINS requires HTTPS origins without paths")
    return RelaySettings(str(address), hostname, origins)


class CreativeView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=8192)
    role: Literal["design7", "it8"] | None = None

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or any(ord(c) < 32 for c in value):
            raise ValueError("url must be an HTTP(S) URL")
        return value


class PrivateHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, settings: RelaySettings):
        super().__init__(settings.hostname, port=443, timeout=5, context=ssl.create_default_context())
        self.private_ip = settings.private_ip

    def connect(self):
        # The TCP destination is private, but SNI and certificate verification
        # use the configured CMS hostname. No environment proxy is consulted.
        sock = socket.create_connection((self.private_ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            self.sock.settimeout(10)
        except BaseException:
            sock.close()
            raise


def forward(settings: RelaySettings, payload: dict) -> JSONResponse:
    connection = PrivateHTTPSConnection(settings)
    try:
        connection.request("POST", PATH, body=json.dumps(payload).encode("utf-8"), headers={
            "Host": settings.hostname,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        response = connection.getresponse()
        # Never follow redirects or retry a request that can write state.
        if not 200 <= response.status < 300 and not 400 <= response.status < 600:
            raise ValueError("Unexpected upstream status")
        if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Unexpected upstream content type")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("Upstream response exceeds limit")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Unexpected upstream JSON")
        return JSONResponse(data, status_code=response.status, headers={"Cache-Control": "no-store"})
    except (socket.timeout, TimeoutError):
        raise HTTPException(504, "CMS confirmation service timed out") from None
    except (OSError, http.client.HTTPException, ValueError):
        raise HTTPException(502, "CMS confirmation service unavailable") from None
    finally:
        connection.close()


@router.post(PATH, include_in_schema=False)
async def creative_view(request: Request):
    settings = request.app.state.creative_relay_settings
    if settings is None:
        raise HTTPException(404, "Not Found")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Content-Type must be application/json")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST:
            raise HTTPException(413, "Request body exceeds limit")
    try:
        payload = CreativeView.model_validate_json(body)
    except (ValidationError, ValueError):
        # Do not echo or log the submitted creative URL.
        raise HTTPException(422, "Invalid creative confirmation request") from None
    return await run_in_threadpool(forward, settings, payload.model_dump())
