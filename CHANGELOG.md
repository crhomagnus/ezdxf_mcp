# Changelog

## 3.2.1 — 2026-07-25

- Prepared a clean public source release with no private infrastructure,
  credentials, screenshots, jobs, or account data.
- Replaced the MIT license with PolyForm Noncommercial License 1.0.0.
- Added explicit commercial-licensing, acceptable-use, security, dependency,
  web-research, and public-validation documentation.
- Reworked deployment templates to require operator-supplied host, IP,
  desktop-user, display, and Xauthority values.
- Documented the evidence boundary: real working results are reported;
  universal site compatibility and zero-ban guarantees are not claimed.

## 3.2.0 — 2026-07-25

- Added an authenticated FastAPI service for PNG/JPG upload, DXF conversion,
  spatial inventory, DXF download, and component queries.
- Added deterministic target selection for centers, boundaries, text
  baselines, relative positions, and safe interior points.
- Added viewport and three-point affine DXF-to-screen calibration.
- Added a restricted, authenticated X11 pointer bridge with confirmation,
  idempotency, rate limiting, and final-position verification.
- Added hardened systemd and SSH deployment templates.
- Added real-screen 1:1 conversion and exact-target validation.
- Corrected repeated movement to the current pixel with an
  `already_at_target` response and mapped bridge failures to HTTP 503.

## 3.1.0 — 2026-07-25

- Added PNG/JPG-to-DXF vectorization with contour hierarchy, circles, curve
  fitting, physical scale, XDATA provenance, and DXF auditing.
- Added Tesseract TSV OCR and native DXF text.
- Added semantic component recognition and WCS spatial relationships.
- Added OCR coordinate transformation for external DXF `IMAGE` entities.
- Expanded the catalog from 115 to 117 tools.

## 3.0.0 — 2026-07-25

- Added a stateful MCP server with 115 DXF tools.
- Added workspace confinement, explicit overwrite, and recovered-document
  write protection.
- Added inspection, audit, geometry, text, rendering, export, and creation
  domains.
- Added synthetic fixtures, regression tests, evaluations, and real MCP stdio
  transport coverage.
