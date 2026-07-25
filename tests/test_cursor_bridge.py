from __future__ import annotations

import pytest

from ezdxf_mcp.cursor.bridge import CursorController, CursorError


class FakeBackend:
    def __init__(self) -> None:
        self.current = (10, 20)
        self.moves: list[tuple[int, int]] = []

    def screen_size(self) -> tuple[int, int]:
        return 1368, 768

    def position(self) -> tuple[int, int]:
        return self.current

    def move(self, x: int, y: int) -> tuple[int, int]:
        self.current = (x, y)
        self.moves.append(self.current)
        return self.current


def test_cursor_bridge_dry_run_does_not_move() -> None:
    backend = FakeBackend()
    controller = CursorController(backend)
    result = controller.execute(
        {
            "request_id": "dry-run-0001",
            "x": 100,
            "y": 200,
            "dry_run": True,
            "confirm": False,
        }
    )
    assert result["status"] == "dry_run"
    assert result["verified_exact"] is True
    assert backend.moves == []


def test_cursor_bridge_moves_exactly_and_deduplicates() -> None:
    backend = FakeBackend()
    controller = CursorController(backend, monotonic=lambda: 10.0)
    payload = {
        "request_id": "move-exact-0001",
        "x": 321,
        "y": 456,
        "dry_run": False,
        "confirm": True,
    }
    result = controller.execute(payload)
    replay = controller.execute(payload)
    assert result["after"] == {"x": 321, "y": 456}
    assert result["verified_exact"] is True
    assert replay["replayed"] is True
    assert backend.moves == [(321, 456)]


def test_cursor_bridge_accepts_target_already_under_pointer() -> None:
    backend = FakeBackend()
    controller = CursorController(backend, monotonic=lambda: 10.0)
    result = controller.execute(
        {
            "request_id": "already-there-0001",
            "x": 10,
            "y": 20,
            "dry_run": False,
            "confirm": True,
        }
    )
    assert result["status"] == "already_at_target"
    assert result["after"] == {"x": 10, "y": 20}
    assert result["verified_exact"] is True
    assert result["movement_performed"] is False
    assert backend.moves == []


def test_cursor_bridge_rejects_outside_screen() -> None:
    controller = CursorController(FakeBackend())
    with pytest.raises(CursorError) as error:
        controller.execute(
            {
                "request_id": "outside-0001",
                "x": 1368,
                "y": 100,
                "dry_run": True,
            }
        )
    assert error.value.code == "outside_screen"
