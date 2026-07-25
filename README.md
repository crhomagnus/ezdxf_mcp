# ezdxf_mcp

**A working visual web-data extraction, image-to-DXF, spatial understanding, and Cartesian targeting engine.**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange.svg)](LICENSE)
[![MCP tools](https://img.shields.io/badge/MCP%20tools-117-5A45FF.svg)](docs/TOOL_CATALOG.md)

`ezdxf_mcp` turns PNG/JPG screenshots into native DXF geometry, recognizes
text and geometric components in Cartesian space, and maps those components
back to exact screen pixels. It combines a stateful MCP server, an authenticated
image-processing API, OCR, vectorization, spatial relationships, and a
strictly limited local cursor bridge.

This is running software, not a mockup or a conceptual demo. The repository
contains the implementation, deterministic fixtures, integration tests,
deployment templates, and a published validation report.

> **License notice:** the source is public for **noncommercial use only** under
> the [PolyForm Noncommercial License 1.0.0](LICENSE). It is source-available,
> not OSI-approved open source. Commercial use requires a separate written
> license; see [Commercial licensing](COMMERCIAL_LICENSE.md).

## What it solves

Most web automation starts with the DOM, a private API, or a platform-specific
selector. `ezdxf_mcp` adds a visual and geometric path:

```text
browser screenshot
       |
       v
PNG/JPG -> OCR + contour hierarchy + vector fitting
       |
       v
1:1 DXF scene -> text, rectangles, circles, curves, polylines
       |
       v
spatial inventory -> identity, bounds, center, containment, distance
       |
       v
Cartesian target -> calibrated screen pixel -> verified pointer movement
```

The result is useful when an authorized research workflow must read and
navigate the same visible interface that a person sees. It is not tied to one
marketplace, browser, product category, language, or website layout.

Typical noncommercial applications include:

- visual price research and product-result extraction;
- interface testing across dynamic layouts;
- screenshot-to-structured-data workflows;
- OCR-assisted extraction when DOM access is unavailable or undesirable;
- CAD and document-image vectorization;
- spatial UI analysis and exact target planning;
- academic research into human-computer interaction.

## Real validation

The current release has been validated with controlled fixtures and live
screen workflows. Public evidence is intentionally aggregate so that accounts,
credentials, private screenshots, and infrastructure are never published.

| Validation | Observed result |
|---|---:|
| MCP/API tools registered | 117 |
| Automated tests | 53 passed |
| Real display conversion | 1368 × 768 at numeric 1:1 scale |
| Components recognized in that frame | 252 |
| OCR text components | 123 |
| Entities outside the viewport | 0 |
| Final cursor error in controlled target tests | 0 pixels |
| Live marketplace workflow | search, scroll, and pagination through pages 2–6 |
| Action pacing in the live workflow | 3 seconds between actions |

Development testing has exercised the approach on multiple web interfaces and
layout types. The public reproducible report currently documents the included
fixtures and one live marketplace workflow. See
[Validation Report](docs/VALIDATION_REPORT.md) for the evidence boundary,
method, limitations, and audit results.

## Platform-agnostic web research

The engine reasons about pixels, OCR text, vector geometry, and screen
coordinates instead of hard-coding one vendor's DOM. A platform adapter can
provide screenshots and authorized input actions while the engine provides:

1. visual capture normalization;
2. OCR and geometric component discovery;
3. component lookup by text or semantic type;
4. exact bounds, centers, distances, and containment relationships;
5. deterministic target-point selection;
6. DXF-to-screen calibration;
7. pointer movement with confirmation and final-position verification.

Dynamic pages still require a fresh capture after scrolling, modal changes,
pagination, responsive reflow, zoom changes, or navigation. The recommended
agent loop is therefore **observe → understand → plan → act → verify**, not a
blind replay of stale coordinates.

Detailed integration guidance is in
[Visual Web Research Automation](docs/WEB_RESEARCH_AUTOMATION.md).

## Respectful automation — no defense bypass

This project is designed for authorized access through ordinary visible user
interfaces. It does **not** provide:

- CAPTCHA solving or bypass;
- login, paywall, or access-control bypass;
- credential theft or session hijacking;
- fingerprint spoofing or anti-bot evasion;
- vulnerability exploitation;
- hidden API abuse;
- automatic acceptance of terms or consent dialogs.

If a website presents a CAPTCHA, authentication request, rate limit, denial,
or other legitimate control, the automation must stop or hand control to an
authorized human. Use the project only where you have permission and in
accordance with applicable law, contractual terms, privacy obligations, and
the website's published rules.

Human-paced visible navigation can reduce anomalous behavior compared with
high-rate request automation. It cannot make account suspension or blocking
impossible. No honest cross-platform system can guarantee a zero or
near-zero ban rate because enforcement is controlled by each independent
service. See [Acceptable Use](ACCEPTABLE_USE.md).

## Core capabilities

### Image to DXF

`dxf_image_to_dxf` accepts PNG, JPG, and JPEG files and:

- preserves nested contours and holes;
- detects circles and fits lines, arcs, Bézier curves, or splines;
- creates native DXF `TEXT` entities from Tesseract TSV OCR;
- preserves source pixel bounding boxes in `IMG2DXF` XDATA;
- supports physical scale by width, DPI, or millimeters per pixel;
- audits the generated DXF before returning it.

### Spatial recognition

`dxf_recognize_components` works on generated and generic DXF files. It
classifies text, raster images, circles, arcs, ellipses, polylines, blocks,
dimensions, and other entities. Each result can include:

- semantic type and source entity types;
- exact or declared-precision WCS bounding box;
- center, dimensions, and component-specific geometry;
- OCR text and confidence where applicable;
- containment, overlap, touch, direction, and distance relationships;
- nearest-component information.

### Exact Cartesian targeting

The targeting API selects a center, boundary point, text baseline, relative
point, or safe interior point. Closed regions with holes use point-in-polygon
tests and a deterministic Cartesian clearance search. Viewport calibration
inverts the Y axis correctly; an affine mode supports rotated or transformed
canvases.

The included bridge can move the pointer only. It has no click, keyboard,
shell, arbitrary URL, or out-of-screen primitive. Movement requires explicit
confirmation and is verified against the final X11 position.

### Full DXF MCP server

The stateful MCP server exposes 117 tools for opening, auditing, querying,
editing, rendering, converting, and creating DXF documents with `ezdxf`
1.4.4. Documents remain resident under a `doc_id`; all file access is confined
to `EZDXF_MCP_WORKSPACE`, and existing files require `overwrite=true`.

See the [Tool Catalog](docs/TOOL_CATALOG.md).

## Installation

Requirements:

- Python 3.10 or later;
- Tesseract OCR plus the language packs needed by your screenshots;
- an X11 desktop and `xdotool` only if pointer movement is required.

```bash
git clone https://github.com/crhomagnus/ezdxf_mcp.git
cd ezdxf_mcp
python3 -m venv .venv
.venv/bin/pip install -e ".[all,dev]"
mkdir -p dxf-workspace
```

For a lightweight MCP-only installation without raster rendering or image
vectorization:

```bash
.venv/bin/pip install -e .
```

## Run the MCP server

```bash
EZDXF_MCP_WORKSPACE="$PWD/dxf-workspace" \
  .venv/bin/ezdxf-mcp
```

Example client registration:

```json
{
  "mcpServers": {
    "ezdxf": {
      "command": "/absolute/path/to/ezdxf_mcp/.venv/bin/ezdxf-mcp",
      "env": {
        "EZDXF_MCP_WORKSPACE": "/absolute/path/to/ezdxf_mcp/dxf-workspace",
        "EZDXF_MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

The process reserves `stdout` for MCP and writes logs to `stderr`.

## Common MCP workflow

```text
dxf_image_to_dxf({
  "image_path": "capture.png",
  "output_path": "capture.dxf",
  "width_mm": 1368
})

dxf_recognize_components({
  "doc_id": "<returned-doc-id>"
})
```

For CAD workflows, open a document once and reuse its `doc_id` across audit,
query, render, edit, and export operations.

## API and deployment

The API accepts authenticated PNG/JPG uploads, persists isolated jobs, exposes
the component inventory and DXF download, and plans calibrated cursor targets.
The reference deployment uses separate Bearer tokens and a dedicated
bidirectional SSH tunnel with loopback-only services.

Start with:

- [API and Cursor Architecture](docs/API_CURSOR_ARCHITECTURE.md)
- [Deployment Guide](deploy/README.md)
- [Image-to-DXF Integration](docs/IMG2DXF_INTEGRATION.md)
- [.env.example](.env.example)

The deployment files are hardened reference templates. Review and adapt users,
display numbers, addresses, paths, memory limits, and firewall policy before
installing them.

## Security model

- Workspace path confinement and explicit overwrite controls.
- Upload type, size, and pixel-count limits.
- Tesseract subprocess timeout with validated arguments and no shell.
- Separate API and cursor credentials stored in mode `0600` files.
- One conversion at a time by default.
- Explicit cursor confirmation, idempotency keys, and rate limiting.
- Loopback binding for API and cursor services.
- No caller-controlled server filesystem paths in API jobs.

Report security issues privately as described in [SECURITY.md](SECURITY.md).
The latest credential-exposure and runtime hardening results are in the
[Security Audit](docs/SECURITY_AUDIT_2026-07-25.md).

## Development

```bash
EZDXF_MCP_WORKSPACE="$PWD/dxf-workspace" .venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m build
```

Fixtures are synthetic and contain no customer or account data.

## Limitations

- OCR quality depends on language packs, contrast, font, resolution, and image
  noise.
- Visual meaning for unlabeled symbols is not universally inferable.
- Complex curve fitting is an approximation unless the source contains exact
  vector data.
- A calibrated screen mapping becomes stale when layout, zoom, pan, scroll,
  modal state, or viewport geometry changes.
- The pointer bridge currently targets X11; Wayland requires a separately
  reviewed desktop-control adapter.
- Site compatibility and account risk cannot be guaranteed.
- This repository is a visual extraction and targeting engine, not permission
  to collect data from third-party services.

## License

Copyright © 2026 Márcio Silva Moreira.

Noncommercial use is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE), subject to its full terms and
the required notice in [NOTICE](NOTICE).

Commercial use — including use in a business, paid service, client project,
revenue-generating workflow, or anticipated commercial application — requires
a separate written agreement. Contact the copyright holder through
[@crhomagnus on GitHub](https://github.com/crhomagnus). Details:
[COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).

Third-party packages remain under their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
