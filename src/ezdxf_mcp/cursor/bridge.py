"""Loopback-only authenticated bridge that moves the X11 mouse pointer."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import stat
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


class CursorError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def load_token(path: Path) -> str:
    file_stat = path.stat()
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise PermissionError(f"token file has unsafe permissions: {path}")
    token = path.read_text(encoding="ascii").strip()
    if len(token) < 32:
        raise ValueError("cursor token is absent or too short")
    return token


@dataclass(frozen=True, slots=True)
class BridgeSettings:
    token_file: Path
    host: str = "127.0.0.1"
    port: int = 3472
    display: str = ":1"
    xauthority: str = "/run/user/1000/gdm/Xauthority"
    xdotool: str = "/usr/bin/xdotool"
    minimum_interval: float = 0.25

    @classmethod
    def from_env(cls) -> BridgeSettings:
        credential_directory = os.getenv("CREDENTIALS_DIRECTORY")
        token_file = os.getenv("EZDXF_CURSOR_TOKEN_FILE")
        if token_file:
            token_path = Path(token_file)
        elif credential_directory:
            token_path = Path(credential_directory) / "cursor-token"
        else:
            token_path = Path("/etc/ezdxf-cursor-bridge/token")
        return cls(
            token_file=token_path,
            host=os.getenv("EZDXF_CURSOR_HOST", "127.0.0.1"),
            port=int(os.getenv("EZDXF_CURSOR_PORT", "3472")),
            display=os.getenv("DISPLAY", ":1"),
            xauthority=os.getenv(
                "XAUTHORITY",
                "/run/user/1000/gdm/Xauthority",
            ),
            xdotool=os.getenv("EZDXF_XDOTOOL", "/usr/bin/xdotool"),
            minimum_interval=float(os.getenv("EZDXF_CURSOR_MIN_INTERVAL", "0.25")),
        )


class XDoToolBackend:
    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings

    def _run(self, *arguments: str) -> str:
        environment = {
            **os.environ,
            "DISPLAY": self.settings.display,
            "XAUTHORITY": self.settings.xauthority,
        }
        result = subprocess.run(
            [self.settings.xdotool, *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
            env=environment,
        )
        return result.stdout.strip()

    def screen_size(self) -> tuple[int, int]:
        width, height = self._run("getdisplaygeometry").split()
        return int(width), int(height)

    def position(self) -> tuple[int, int]:
        values: dict[str, str] = {}
        for line in self._run("getmouselocation", "--shell").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        return int(values["X"]), int(values["Y"])

    def move(self, x: int, y: int) -> tuple[int, int]:
        self._run("mousemove", "--sync", str(x), str(y))
        return self.position()


class CursorController:
    """Validate, rate-limit, deduplicate and execute exact pointer moves."""

    def __init__(
        self,
        backend: Any,
        *,
        minimum_interval: float = 0.25,
        monotonic: Any = time.monotonic,
    ) -> None:
        self.backend = backend
        self.minimum_interval = minimum_interval
        self.monotonic = monotonic
        self.last_move = float("-inf")
        self.results: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
            raise CursorError(400, "invalid_request_id", "request_id is invalid")
        if request_id in self.results:
            return {**self.results[request_id], "replayed": True}
        x = payload.get("x")
        y = payload.get("y")
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
            raise CursorError(400, "invalid_coordinate", "x and y must be integers")
        width, height = self.backend.screen_size()
        if not 0 <= x < width or not 0 <= y < height:
            raise CursorError(
                422,
                "outside_screen",
                f"target ({x}, {y}) is outside {width}x{height}",
            )
        dry_run = bool(payload.get("dry_run", True))
        confirm = payload.get("confirm") is True
        if not dry_run and not confirm:
            raise CursorError(409, "confirmation_required", "actual move requires confirm=true")
        before = self.backend.position()
        if dry_run:
            after = before
            status = "dry_run"
        elif before == (x, y):
            after = before
            status = "already_at_target"
        else:
            now = float(self.monotonic())
            if now - self.last_move < self.minimum_interval:
                raise CursorError(429, "rate_limited", "cursor movement is rate limited")
            after = self.backend.move(x, y)
            self.last_move = now
            status = "moved"
            if after != (x, y):
                raise CursorError(
                    500,
                    "position_mismatch",
                    f"pointer stopped at {after}, expected {(x, y)}",
                )
        result = {
            "status": status,
            "request_id": request_id,
            "target": {"x": x, "y": y},
            "before": {"x": before[0], "y": before[1]},
            "after": {"x": after[0], "y": after[1]},
            "screen": {"width": width, "height": height},
            "verified_exact": dry_run or after == (x, y),
            "movement_performed": not dry_run and before != (x, y),
            "capabilities": ["cursor_move"],
            "replayed": False,
        }
        self.results[request_id] = result
        while len(self.results) > 256:
            self.results.popitem(last=False)
        return result


def make_handler(
    controller: CursorController,
    token: str,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ezdxf-cursor-bridge/1"

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            authorization = self.headers.get("Authorization", "")
            scheme, _, candidate = authorization.partition(" ")
            return scheme.lower() == "bearer" and hmac.compare_digest(candidate, token)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._json(404, {"error": "not_found"})
                return
            width, height = controller.backend.screen_size()
            self._json(
                200,
                {
                    "status": "ok",
                    "screen": {"width": width, "height": height},
                    "capabilities": ["cursor_move"],
                },
            )

        def do_POST(self) -> None:
            if self.path != "/v1/cursor/move":
                self._json(404, {"error": "not_found"})
                return
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 1 <= length <= 4096:
                self._json(413, {"error": "invalid_body_size"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("JSON body must be an object")
                result = controller.execute(payload)
                self._json(200, result)
            except CursorError as error:
                self._json(
                    error.status,
                    {"error": error.code, "message": error.message},
                )
            except (json.JSONDecodeError, ValueError) as error:
                self._json(400, {"error": "invalid_json", "message": str(error)})

        def do_PUT(self) -> None:
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})

        def do_DELETE(self) -> None:
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})

        def log_message(self, format: str, *args: Any) -> None:
            print(
                json.dumps(
                    {
                        "remote": self.client_address[0],
                        "request": format % args,
                    }
                ),
                flush=True,
            )

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate display and exit")
    args = parser.parse_args()
    settings = BridgeSettings.from_env()
    if settings.host not in {"127.0.0.1", "::1"}:
        raise SystemExit("cursor bridge refuses non-loopback bind")
    token = load_token(settings.token_file)
    backend = XDoToolBackend(settings)
    if args.check:
        print(
            json.dumps(
                {
                    "screen": backend.screen_size(),
                    "position": backend.position(),
                }
            )
        )
        return
    controller = CursorController(
        backend,
        minimum_interval=settings.minimum_interval,
    )
    server = HTTPServer(
        (settings.host, settings.port),
        make_handler(controller, token),
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
