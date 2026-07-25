# API and Cartesian Cursor Architecture

Release: 3.2.2

## Reference topology

```text
local agent
    |
    | HTTP Bearer, loopback
    v
SSH local forward
    |
    v
remote VM: FastAPI + image-to-DXF + OCR + spatial analysis
    |
    | HTTP Bearer, loopback
    v
SSH reverse forward
    |
    v
graphical host: restricted X11 pointer movement
```

The reference design uses a single dedicated SSH connection for both
forwards. The remote tunnel account has no shell, password, TTY, SFTP, agent
forwarding, or X11 forwarding. `PermitOpen` and `PermitListen` restrict the
only allowed endpoints.

The API and cursor bridge bind to loopback by default. Do not expose either
service directly to the public internet.

## Authentication

`GET /health` returns only service status and version information. All other
API routes require:

```text
Authorization: Bearer <api-token>
```

Create independent API and cursor tokens, each at least 32 random characters,
and store them in mode `0600` regular files outside the repository. The path
below is an example placeholder, not a real credential location:

```bash
API_TOKEN_FILE=/secure/path/ezdxf-api-token
API_TOKEN=$(tr -d '\r\n' < "$API_TOKEN_FILE")
```

## Convert an image

```bash
curl --noproxy '*' \
  -H "Authorization: Bearer $API_TOKEN" \
  -F 'file=@capture.png;type=image/png' \
  -F 'options={"width_mm":1368,"curve_mode":"line","run_text_ocr":true}' \
  http://127.0.0.1:8766/v1/convert
```

The response includes a job ID, scale, drawing bounds, semantic counts,
warnings, and the DXF download URL. The default service accepts PNG/JPG/JPEG
uploads up to 50 MiB and allows one conversion at a time.

## Query components

```bash
curl --noproxy '*' \
  -H "Authorization: Bearer $API_TOKEN" \
  'http://127.0.0.1:8766/v1/jobs/JOB_ID/components?text=SIGN%20IN'
```

Filters can select recognized text or a semantic type such as `circle`,
`rectangle`, or `polyline`. Results preserve component IDs, DXF handles,
geometry, WCS bounding boxes, spatial relationships, and precision labels.

## Plan a target without moving

```json
{
  "component_id": "text_0001",
  "strategy": "center",
  "calibration": {
    "mode": "viewport",
    "fit": "contain",
    "screen": {
      "left": 0,
      "top": 0,
      "width": 1368,
      "height": 768
    }
  }
}
```

Send the object to:

```text
POST /v1/jobs/JOB_ID/cursor/plan
```

Available strategies:

- `interior`: a safe interior point that excludes holes;
- `center`: the bounding-box center;
- `boundary`: a deterministic point on the boundary;
- `text_baseline`: the native text insertion point;
- `relative`: interpolation within the component bounds.

## Move the pointer

Use the same request body with `/cursor/move` and add:

```json
{
  "dry_run": false,
  "confirm_move": true,
  "request_id": "unique-operation-id"
}
```

Without explicit confirmation, the API returns HTTP 409. Reusing a
`request_id` returns the stored result without repeating movement.

The bridge intentionally implements pointer movement only. It has no click,
keyboard, shell, arbitrary URL, or out-of-screen primitive.

## Target selection

The deterministic target algorithm:

1. locates entities by component XDATA or DXF handle;
2. reconstructs closed regions from flattened lines, arcs, splines, and
   polylines;
3. uses analytical centers for circles and insertion points for text;
4. computes polygon centroids and validates them with ray casting;
5. excludes holes using contour hierarchy;
6. evaluates a Cartesian grid if the center is invalid;
7. chooses the valid point with the greatest boundary clearance.

This avoids targeting empty space at the center of a ring or hollow shape.

## DXF-to-screen calibration

For drawing bounds `(xmin, ymin)` to `(xmax, ymax)`:

```text
pixel_x = offset_x + (x - xmin) * scale_x
pixel_y = offset_y + (ymax - y) * scale_y
```

The Y axis is inverted because WCS coordinates increase upward while screen
pixels increase downward. `contain` preserves aspect ratio and centers the
drawing; `stretch` uses independent X and Y scales.

For rotated or transformed canvases, affine calibration accepts exactly three
non-collinear DXF/screen point pairs and solves the six affine coefficients.
The API rejects collinear pairs, non-finite results, and pixels outside the
declared screen.

## Operational rule

A target is valid only while the captured scene and viewport calibration
remain valid. Recapture after navigation, scrolling, responsive reflow,
modal changes, browser zoom, CAD zoom, or window movement.

## Security checklist

- Loopback binding or a private authenticated network only.
- Independent API and cursor tokens.
- Tokens and private keys outside the repository with mode `0600`.
- Dedicated unprivileged service and tunnel users.
- SSH `PermitOpen`/`PermitListen` restrictions.
- Explicit movement confirmation and idempotency.
- Upload limits, one conversion at a time, and isolated job directories.
- No caller-controlled server paths.
- No public screenshots or extracted account data.
