from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from ezdxf_mcp.api.app import ApiSettings, ConversionOptions, create_app


class FakeCursorClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def move(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        return {
            "status": "dry_run" if payload["dry_run"] else "moved",
            "target": {"x": payload["x"], "y": payload["y"]},
            "after": {"x": payload["x"], "y": payload["y"]},
            "verified_exact": True,
        }


def _token(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="ascii")
    os.chmod(path, 0o600)


def test_conversion_options_expose_bounded_ocr_timeout() -> None:
    assert (
        ConversionOptions(ocr_timeout=180).vectorization_config().ocr_timeout
        == 180
    )
    with pytest.raises(ValueError):
        ConversionOptions(ocr_timeout=601)


@pytest.mark.asyncio
async def test_api_conversion_recognition_plan_and_move(
    workspace: Path,
    tmp_path: Path,
) -> None:
    api_token = "a" * 48
    api_token_path = tmp_path / "api-token"
    cursor_token_path = tmp_path / "cursor-token"
    _token(api_token_path, api_token)
    _token(cursor_token_path, "b" * 48)
    fake_cursor = FakeCursorClient()
    app = create_app(
        ApiSettings(
            workspace=tmp_path / "api-workspace",
            api_token_file=api_token_path,
            cursor_token_file=cursor_token_path,
        ),
        cursor_client=fake_cursor,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    assert (await client.get("/health")).status_code == 200

    image_path = workspace / "componentes.png"
    options = {
        "width_mm": 200,
        "run_text_ocr": False,
        "curve_mode": "line",
    }
    with image_path.open("rb") as image:
        unauthorized = await client.post(
            "/v1/convert",
            files={"file": ("componentes.png", image.read(), "image/png")},
            data={"options": json.dumps(options)},
        )
    assert unauthorized.status_code == 401

    with image_path.open("rb") as image:
        converted = await client.post(
            "/v1/convert",
            headers={"Authorization": f"Bearer {api_token}"},
            files={"file": ("componentes.png", image.read(), "image/png")},
            data={"options": json.dumps(options)},
        )
    assert converted.status_code == 200, converted.text
    conversion = converted.json()
    assert conversion["component_count"] >= 3
    job_id = conversion["job_id"]

    components_response = await client.get(
        f"/v1/jobs/{job_id}/components",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    components = components_response.json()["components"]
    circle = next(
        component for component in components if component["semantic_type"] == "circle"
    )
    request_body = {
        "component_id": circle["component_id"],
        "strategy": "interior",
        "calibration": {
            "mode": "viewport",
            "fit": "stretch",
            "screen": {"left": 0, "top": 0, "width": 1368, "height": 768},
        },
    }
    plan = await client.post(
        f"/v1/jobs/{job_id}/cursor/plan",
        headers={"Authorization": f"Bearer {api_token}"},
        json=request_body,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["target"]["point_wcs"] == [140.0, 52.5, 0.0]

    moved = await client.post(
        f"/v1/jobs/{job_id}/cursor/move",
        headers={"Authorization": f"Bearer {api_token}"},
        json={
            **request_body,
            "dry_run": False,
            "confirm_move": True,
            "request_id": "api-move-0001",
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["bridge"]["verified_exact"] is True
    assert fake_cursor.payloads[0]["confirm"] is True

    downloaded = await client.get(
        f"/v1/jobs/{job_id}/drawing.dxf",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"  0\nSECTION")
    await client.aclose()


@pytest.mark.asyncio
async def test_api_rejects_body_before_multipart_parsing(tmp_path: Path) -> None:
    api_token = "c" * 48
    api_token_path = tmp_path / "api-token"
    cursor_token_path = tmp_path / "cursor-token"
    _token(api_token_path, api_token)
    _token(cursor_token_path, "d" * 48)
    app = create_app(
        ApiSettings(
            workspace=tmp_path / "limited-workspace",
            api_token_file=api_token_path,
            cursor_token_file=cursor_token_path,
            max_upload_mb=0,
        ),
        cursor_client=FakeCursorClient(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/convert",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/octet-stream",
            },
            content=b"x" * (1024 * 1024 + 1),
        )
    assert response.status_code == 413
