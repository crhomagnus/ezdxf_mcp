# Public Validation Report

Date: 2026-07-25

Release candidate: 3.2.1

## Conclusion

The release is functional and test-backed. The image-to-DXF pipeline,
component recognition, Cartesian calibration, API authentication, and
restricted cursor movement were exercised through automated tests and
controlled real-screen trials.

The evidence supports exact pointer placement under a valid calibration. It
does not support claims of universal OCR accuracy, guaranteed compatibility
with every website, or a guaranteed ban rate.

## Automated verification

The release gate runs:

```bash
EZDXF_MCP_WORKSPACE="$PWD/dxf-workspace" .venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m build
```

Observed release-candidate results:

| Check | Result |
|---|---|
| Pytest | 38 passed |
| Ruff | passed |
| Mypy | passed for 38 source files |
| Wheel and source distribution | built successfully |
| MCP tool catalog | 117 unique tools exercised |
| Real MCP stdio transport | passed |

All committed test images and DXF fixtures are synthetic.

## Controlled real-screen evidence

A 1368 × 768 browser frame was converted with a numeric 1:1 mapping:

| Measurement | Result |
|---|---:|
| Drawing bounds | `(0, 0)` to `(1368, 768)` |
| Recognized components | 252 |
| OCR text components | 123 |
| Recognized rectangles | 4 |
| Entities outside viewport | 0 |
| DXF audit errors | 0 |

Text labels and close controls were resolved from the current frame and mapped
back to screen pixels. The bridge and X11 position query agreed on each final
coordinate. Controlled acceptance targets recorded zero-pixel final pointer
error.

That result means **the pointer reached the calculated pixel**. Whether the
pixel remains visually correct depends on preserving the exact viewport,
window geometry, scroll state, zoom, and page state used by calibration.

## Live web workflow

Under explicit human authorization, a live marketplace workflow:

- dismissed visible login notices without bypassing authentication;
- entered a product query through the normal interface;
- scrolled visible results;
- navigated sequentially from page 2 through page 6;
- used three seconds between actions;
- made no purchase, login, message, or hidden API request.

The target was recaptured after scrolling because its pixel position changed.
This validated the observe-understand-act-verify rule for dynamic pages.

Development testing has also exercised multiple web interfaces and layout
types. Those additional sessions are not presented as public reproducible
benchmarks because their raw frames can contain private account or
infrastructure data.

## Security verification

- API requests without a valid Bearer token return HTTP 401.
- Cursor movement without explicit confirmation returns HTTP 409.
- Out-of-screen coordinates are rejected.
- Repeated request IDs do not repeat movement.
- API and cursor services are designed to bind to loopback.
- The cursor bridge exposes no click, keyboard, shell, or arbitrary URL
  operation.
- Release content was scanned for common private-key, access-token, credential
  assignment, JWT, and credential-in-URL patterns before publication.
- Internal screenshots, DXF jobs, tokens, hostnames, IP addresses, and private
  operational records are excluded from the public release.

## Risk assessment

Resolved or controlled:

- stale repeated-pointer targets return `already_at_target`;
- bridge transport failures become HTTP 503;
- OCR boxes that are implausibly large are rejected;
- source pixel boxes are preserved in XDATA;
- paths are confined to a configured workspace;
- movement is explicit, rate-limited, and idempotent.

Residual:

- OCR remains probabilistic;
- unlabeled symbols may be semantically ambiguous;
- curve fitting approximates raster input;
- screen coordinates become stale after visual changes;
- X11 desktop access inherits the security boundary of the graphical user;
- job expiration is an operational responsibility;
- third-party websites independently decide whether and how automation is
  allowed.

## Claims boundary

Supported:

- the project is real, executable, and test-backed;
- the architecture is not hard-coded to one web platform;
- visible text and geometry can be extracted from screenshots;
- calibrated pointer movement can be exact at the pixel level;
- human-paced sequential navigation has worked in a live workflow.

Not claimed:

- CAPTCHA, login, paywall, or anti-bot bypass;
- undetectability;
- universal semantic understanding;
- guaranteed operation on every site;
- zero or near-zero suspension risk.
