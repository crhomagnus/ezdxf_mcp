from __future__ import annotations

import os
from pathlib import Path

import pytest

from ezdxf_mcp.api.app import ApiSettings, CursorClient
from ezdxf_mcp.security import load_secret_file


def _secret(path: Path, value: str = "s" * 48) -> Path:
    path.write_text(value + "\n", encoding="ascii")
    os.chmod(path, 0o600)
    return path


def _settings(tmp_path: Path, **overrides: object) -> ApiSettings:
    values: dict[str, object] = {
        "workspace": tmp_path / "workspace",
        "api_token_file": _secret(tmp_path / "api-token", "a" * 48),
        "cursor_token_file": _secret(tmp_path / "cursor-token", "b" * 48),
    }
    values.update(overrides)
    return ApiSettings(**values)  # type: ignore[arg-type]


def test_load_secret_file_accepts_private_regular_file(tmp_path: Path) -> None:
    path = _secret(tmp_path / "token")
    assert load_secret_file(path) == "s" * 48


def test_load_secret_file_rejects_group_permissions(tmp_path: Path) -> None:
    path = _secret(tmp_path / "token")
    os.chmod(path, 0o640)
    with pytest.raises(PermissionError, match="unsafe permissions"):
        load_secret_file(path)


def test_load_secret_file_rejects_symbolic_link(tmp_path: Path) -> None:
    target = _secret(tmp_path / "target")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(PermissionError, match="symbolic link"):
        load_secret_file(link)


def test_load_secret_file_rejects_hard_link(tmp_path: Path) -> None:
    target = _secret(tmp_path / "target")
    link = tmp_path / "hard-link"
    os.link(target, link)
    with pytest.raises(PermissionError, match="exactly one hard link"):
        load_secret_file(target)


def test_load_secret_file_rejects_embedded_whitespace(tmp_path: Path) -> None:
    path = _secret(tmp_path / "token", "a" * 32 + " " + "b" * 32)
    with pytest.raises(ValueError, match="without whitespace"):
        load_secret_file(path)


@pytest.mark.parametrize(
    "cursor_url",
    [
        "file:///etc/passwd",
        "https://127.0.0.1:3472",
        "http://localhost:3472",
        "http://192.0.2.10:3472",
        "http://user:secret@127.0.0.1:3472",
        "http://127.0.0.1:3472/unexpected",
        "http://127.0.0.1",
    ],
)
def test_api_rejects_cursor_urls_outside_fixed_loopback_boundary(
    tmp_path: Path,
    cursor_url: str,
) -> None:
    with pytest.raises(ValueError, match="cursor bridge URL"):
        _settings(tmp_path, cursor_url=cursor_url).validate_security_boundary()


def test_api_rejects_non_loopback_bind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-loopback bind"):
        _settings(tmp_path, bind_host="0.0.0.0").validate_security_boundary()


def test_api_accepts_literal_loopback_boundaries(tmp_path: Path) -> None:
    _settings(tmp_path).validate_security_boundary()
    _settings(
        tmp_path,
        bind_host="::1",
        cursor_url="http://[::1]:3472",
    ).validate_security_boundary()


def test_cursor_client_rejects_non_loopback_destination(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="literal loopback"):
        CursorClient(
            "http://example.com:3472",
            _secret(tmp_path / "cursor-token"),
            1.0,
        )
