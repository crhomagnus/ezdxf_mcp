from __future__ import annotations

import pytest

from ezdxf_mcp.formatting import paginate, response


def test_pagination() -> None:
    page = paginate(list(range(10)), limit=3, offset=3)
    assert page["items"] == [3, 4, 5]
    assert page["total"] == 10
    assert page["has_more"] is True


def test_invalid_pagination() -> None:
    with pytest.raises(ValueError):
        paginate([], limit=0)


def test_markdown_response_keeps_machine_data() -> None:
    result = response({"ok": True}, "markdown")
    assert result["format"] == "markdown"
    assert result["data"] == {"ok": True}
