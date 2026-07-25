"""Authenticated FastAPI service for image-to-DXF and exact cursor movement."""

from __future__ import annotations

import hmac
import http.client
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import SplitResult, urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..image.targeting import select_component_target
from ..image.vectorize import IMAGE_SUFFIXES, ImageVectorizationConfig
from ..security import load_secret_file
from .calibration import map_wcs_to_screen
from .jobs import JobStore


def _secure_token(path: Path) -> str:
    return load_secret_file(path)


def _loopback_http_url(raw_url: str) -> SplitResult:
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("cursor bridge URL is invalid") from error
    if parsed.scheme != "http":
        raise ValueError("cursor bridge URL must use plain HTTP inside the SSH tunnel")
    if parsed.hostname not in {"127.0.0.1", "::1"}:
        raise ValueError("cursor bridge URL must use a literal loopback address")
    if port is None:
        raise ValueError("cursor bridge URL must include an explicit port")
    if parsed.username or parsed.password:
        raise ValueError("cursor bridge URL must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("cursor bridge URL must not contain a path, query, or fragment")
    return parsed


@dataclass(frozen=True, slots=True)
class ApiSettings:
    workspace: Path
    api_token_file: Path
    cursor_token_file: Path
    cursor_url: str = "http://127.0.0.1:3472"
    max_upload_mb: int = 50
    cursor_timeout: float = 5.0
    bind_host: str = "127.0.0.1"
    bind_port: int = 8766

    def validate_security_boundary(self) -> None:
        if self.bind_host not in {"127.0.0.1", "::1"}:
            raise ValueError("API refuses a non-loopback bind")
        if not 1 <= self.bind_port <= 65535:
            raise ValueError("API port must be between 1 and 65535")
        _loopback_http_url(self.cursor_url)

    @classmethod
    def from_env(cls) -> ApiSettings:
        credential_directory = os.getenv("CREDENTIALS_DIRECTORY")

        def credential(name: str, fallback: str) -> Path:
            explicit = os.getenv(name)
            if explicit:
                return Path(explicit)
            if credential_directory:
                filename = "api-token" if name == "EZDXF_API_TOKEN_FILE" else "cursor-token"
                return Path(credential_directory) / filename
            return Path(fallback)

        return cls(
            workspace=Path(
                os.getenv("EZDXF_API_WORKSPACE", "/var/lib/ezdxf-api")
            ).resolve(),
            api_token_file=credential(
                "EZDXF_API_TOKEN_FILE",
                "/etc/ezdxf-api/api-token",
            ),
            cursor_token_file=credential(
                "EZDXF_CURSOR_TOKEN_FILE",
                "/etc/ezdxf-api/cursor-token",
            ),
            cursor_url=os.getenv(
                "EZDXF_CURSOR_BRIDGE_URL",
                "http://127.0.0.1:3472",
            ).rstrip("/"),
            max_upload_mb=int(os.getenv("EZDXF_API_MAX_UPLOAD_MB", "50")),
            cursor_timeout=float(os.getenv("EZDXF_CURSOR_TIMEOUT", "5")),
            bind_host=os.getenv("EZDXF_API_HOST", "127.0.0.1"),
            bind_port=int(os.getenv("EZDXF_API_PORT", "8766")),
        )


class ConversionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width_mm: float | None = Field(default=None, gt=0)
    dpi: float | None = Field(default=None, gt=0)
    mm_per_pixel: float | None = Field(default=None, gt=0)
    curve_mode: Literal["auto", "arc", "bezier", "line", "spline"] = "auto"
    binarization: Literal["otsu", "fixed", "adaptive", "canny"] = "otsu"
    threshold: int = Field(default=127, ge=0, le=255)
    invert: bool = False
    blur: int = Field(default=3, ge=0, le=31)
    canny_low: int = Field(default=50, ge=0, le=254)
    canny_high: int = Field(default=150, ge=1, le=255)
    fit_tolerance_px: float = Field(default=0.8, gt=0, le=100)
    max_arc_angle: float = Field(default=120.0, gt=0, le=180)
    simplify_fraction: float = Field(default=0.002, ge=0, le=1)
    minimum_area_px: float = Field(default=20.0, ge=0)
    run_text_ocr: bool = True
    ocr_language: str = "por+eng"
    ocr_page_segmentation_mode: int = Field(default=11, ge=0, le=13)
    ocr_min_confidence: float = Field(default=50.0, ge=-1, le=100)
    ocr_timeout: float = Field(default=60.0, gt=0, le=600)
    exclude_ocr_from_vectors: bool = True
    include_raster_reference: bool = False

    def vectorization_config(self) -> ImageVectorizationConfig:
        config = ImageVectorizationConfig(**self.model_dump())
        config.validate()
        return config


class ScreenRect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: int = Field(default=0, ge=0)
    top: int = Field(default=0, ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class DrawingBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: list[float] = Field(min_length=2, max_length=3)
    max: list[float] = Field(min_length=2, max_length=3)


class CalibrationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing: list[float] = Field(min_length=2, max_length=2)
    screen: list[float] = Field(min_length=2, max_length=2)


class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["viewport", "affine"] = "viewport"
    screen: ScreenRect
    fit: Literal["contain", "stretch"] = "contain"
    drawing: DrawingBounds | None = None
    pairs: list[CalibrationPair] | None = None


class CursorTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=200)
    strategy: Literal[
        "interior",
        "center",
        "boundary",
        "text_baseline",
        "relative",
    ] = "interior"
    relative_x: float = Field(default=0.5, ge=0, le=1)
    relative_y: float = Field(default=0.5, ge=0, le=1)
    calibration: Calibration


class CursorMoveRequest(CursorTargetRequest):
    dry_run: bool = True
    confirm_move: bool = False
    request_id: str | None = Field(default=None, min_length=8, max_length=100)


class CursorClient:
    """Fixed-destination client for the loopback-only cursor bridge."""

    def __init__(self, base_url: str, token_file: Path, timeout: float) -> None:
        parsed = _loopback_http_url(base_url)
        host = parsed.hostname
        port = parsed.port
        if host is None or port is None:
            raise ValueError("cursor bridge URL is missing its host or port")
        self.host = host
        self.port = port
        self.token_file = token_file
        self.timeout = timeout

    def move(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = _secure_token(self.token_file)
        body = json.dumps(payload).encode("utf-8")
        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=self.timeout,
        )
        try:
            connection.request(
                "POST",
                "/v1/cursor/move",
                body=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()
            response_body = response.read().decode("utf-8", errors="replace")
            if not 200 <= response.status < 300:
                raise RuntimeError(
                    f"cursor bridge HTTP {response.status}: {response_body}"
                )
            return json.loads(response_body)
        except OSError as error:
            raise RuntimeError(f"cursor bridge unavailable: {error}") from error
        finally:
            connection.close()


class RequestTooLarge(Exception):
    """Raised by the ASGI receive wrapper before multipart parsing can grow."""


class RequestSizeLimitMiddleware:
    def __init__(self, app: Any, maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        raw_length = headers.get(b"content-length")
        try:
            declared_length = int(raw_length) if raw_length is not None else None
        except ValueError:
            response = JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            await response(scope, receive, send)
            return
        if declared_length is not None and declared_length > self.maximum_bytes:
            response = JSONResponse({"detail": "request body too large"}, status_code=413)
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.maximum_bytes:
                    raise RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            response = JSONResponse({"detail": "request body too large"}, status_code=413)
            await response(scope, receive, send)


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    recognition = result["recognition"]
    return {
        "job_id": result["job_id"],
        "status": result["status"],
        "created_at": result["created_at"],
        "dxf_url": f"/v1/jobs/{result['job_id']}/drawing.dxf",
        "component_count": recognition["component_count"],
        "semantic_counts": recognition["semantic_counts"],
        "drawing_bounds": result["drawing_bounds"],
        "conversion": result["conversion"],
    }


def create_app(
    settings: ApiSettings | None = None,
    *,
    cursor_client: CursorClient | Any | None = None,
) -> FastAPI:
    configured = settings or ApiSettings.from_env()
    configured.validate_security_boundary()
    api_token = _secure_token(configured.api_token_file)
    jobs = JobStore(configured.workspace / "jobs")
    cursor = cursor_client or CursorClient(
        configured.cursor_url,
        configured.cursor_token_file,
        configured.cursor_timeout,
    )
    security = HTTPBearer(auto_error=False)
    conversion_lock = threading.Lock()

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials, api_token)
        ):
            raise HTTPException(status_code=401, detail="invalid bearer token")

    app = FastAPI(
        title="ezdxf Image Spatial API",
        version=__version__,
        description=(
            "Convert PNG/JPG to native DXF, recognize Cartesian components, "
            "map targets to a calibrated screen, and move only the mouse pointer."
        ),
    )
    app.add_middleware(
        RequestSizeLimitMiddleware,
        maximum_bytes=(configured.max_upload_mb + 1) * 1024 * 1024,
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "api_bind_policy": "loopback_only",
            "cursor_capability": "move_only_no_click_no_keyboard",
        }

    @app.post("/v1/convert", dependencies=[Depends(authenticate)])
    async def convert(
        file: Annotated[UploadFile, File(description="PNG or JPG image")],
        options: Annotated[str, Form()] = "{}",
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise HTTPException(status_code=415, detail="only PNG/JPG/JPEG are accepted")
        try:
            parsed_options = ConversionOptions.model_validate_json(options)
            config = parsed_options.vectorization_config()
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not conversion_lock.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="another conversion is in progress")
        job_id = ""
        try:
            job_id, _directory, source_path = jobs.create(suffix)
            maximum = configured.max_upload_mb * 1024 * 1024
            total = 0
            with source_path.open("xb") as output:
                while block := await file.read(1024 * 1024):
                    total += len(block)
                    if total > maximum:
                        raise HTTPException(
                            status_code=413,
                            detail=f"upload exceeds {configured.max_upload_mb} MB",
                        )
                    output.write(block)
            result = await run_in_threadpool(
                jobs.convert,
                job_id=job_id,
                source_path=source_path,
                config=config,
            )
            return _summary(result)
        except HTTPException:
            if job_id:
                jobs.remove(job_id)
            raise
        except Exception as error:
            if job_id:
                jobs.remove(job_id)
            raise HTTPException(
                status_code=400,
                detail=f"conversion failed: {type(error).__name__}: {error}",
            ) from error
        finally:
            conversion_lock.release()
            await file.close()

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(authenticate)])
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return jobs.result(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/v1/jobs/{job_id}/components", dependencies=[Depends(authenticate)])
    def get_components(
        job_id: str,
        semantic_type: str | None = Query(default=None),
        text: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            components = jobs.result(job_id)["recognition"]["components"]
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if semantic_type:
            components = [
                component
                for component in components
                if component.get("semantic_type") == semantic_type
            ]
        if text:
            needle = text.casefold()

            def component_text(component: dict[str, Any]) -> str:
                details = component.get("details")
                values = details if isinstance(details, list) else [details]
                return " ".join(
                    str(item.get("text", ""))
                    for item in values
                    if isinstance(item, dict)
                )

            components = [
                component
                for component in components
                if needle in component_text(component).casefold()
            ]
        return {"job_id": job_id, "count": len(components), "components": components}

    @app.get("/v1/jobs/{job_id}/drawing.dxf", dependencies=[Depends(authenticate)])
    def download_dxf(job_id: str) -> FileResponse:
        try:
            path = jobs.dxf_path(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type="image/vnd.dxf", filename=f"{job_id}.dxf")

    def plan_target(job_id: str, body: CursorTargetRequest) -> dict[str, Any]:
        try:
            result = jobs.result(job_id)
            document = jobs.open_document(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        try:
            target = select_component_target(
                layout=document.modelspace(),
                components=result["recognition"]["components"],
                component_id=body.component_id,
                strategy=body.strategy,
                relative_x=body.relative_x,
                relative_y=body.relative_y,
            )
            mapped = map_wcs_to_screen(
                target["point_wcs"],
                body.calibration.model_dump(exclude_none=True),
                result["drawing_bounds"],
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "job_id": job_id,
            "target": target,
            "mapping": mapped,
        }

    @app.post(
        "/v1/jobs/{job_id}/cursor/plan",
        dependencies=[Depends(authenticate)],
    )
    def cursor_plan(job_id: str, body: CursorTargetRequest) -> dict[str, Any]:
        return plan_target(job_id, body)

    @app.post(
        "/v1/jobs/{job_id}/cursor/move",
        dependencies=[Depends(authenticate)],
    )
    async def cursor_move(job_id: str, body: CursorMoveRequest) -> dict[str, Any]:
        if not body.dry_run and not body.confirm_move:
            raise HTTPException(
                status_code=409,
                detail="actual cursor movement requires confirm_move=true",
            )
        plan = plan_target(job_id, body)
        screen = plan["mapping"]["screen_pixel"]
        request_id = body.request_id or uuid4().hex
        payload = {
            "request_id": request_id,
            "x": screen["x"],
            "y": screen["y"],
            "dry_run": body.dry_run,
            "confirm": body.confirm_move,
        }
        try:
            bridge_result = await run_in_threadpool(cursor.move, payload)
        except (OSError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            **plan,
            "request_id": request_id,
            "dry_run": body.dry_run,
            "bridge": bridge_result,
        }

    app.state.settings = configured
    app.state.jobs = jobs
    app.state.cursor = cursor
    return app


def main() -> None:
    import uvicorn

    settings = ApiSettings.from_env()
    settings.validate_security_boundary()
    uvicorn.run(
        "ezdxf_mcp.api.app:create_app",
        factory=True,
        host=settings.bind_host,
        port=settings.bind_port,
        workers=1,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
