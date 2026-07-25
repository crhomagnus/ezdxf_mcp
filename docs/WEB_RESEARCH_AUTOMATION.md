# Visual Web Research Automation

## Scope

`ezdxf_mcp` is a platform-agnostic visual extraction and targeting layer for
authorized web research. It observes the rendered interface rather than
depending on a particular site's private API or DOM structure.

It can be connected to an agent that captures a browser frame and performs
authorized input actions. The included cursor bridge deliberately moves only
the pointer; click and keyboard adapters are outside its security boundary.

## Recommended agent loop

```text
OBSERVE
  capture the current browser viewport and metadata
      |
UNDERSTAND
  convert to 1:1 DXF, run OCR, inventory components
      |
PLAN
  resolve a target by text/type/relationship and choose a safe point
      |
POLICY GATE
  verify authorization, page state, action type, and pacing
      |
ACT
  move the pointer; an approved adapter may click or type
      |
VERIFY
  capture again and confirm the expected state change
```

Never reuse coordinates after a visual state change. Scrolling, pagination,
modal changes, responsive reflow, browser zoom, and navigation invalidate the
previous scene.

## Structured extraction

A research adapter can normalize recognized components into records such as:

```json
{
  "source_url": "https://example.invalid/search",
  "captured_at": "2026-07-25T12:00:00Z",
  "viewport": {"width": 1368, "height": 768},
  "record": {
    "title": "Example product",
    "price": "123.45",
    "currency": "CNY",
    "seller": "Example seller"
  },
  "evidence": {
    "title_component_id": "text_0042",
    "price_component_id": "text_0047",
    "screen_bounds": [410, 220, 730, 355]
  }
}
```

The adapter, not the geometry engine, defines platform-specific record fields.
Raw OCR values should be preserved alongside normalized values so a human can
audit the extraction.

## Platform adaptation

A new platform normally needs configuration rather than changes to the
vectorization core:

- browser viewport capture;
- language packs and OCR thresholds;
- text aliases for search, pagination, close, next, or product fields;
- component relationship rules;
- approved pacing;
- stop conditions and human handoff rules;
- a record normalizer for the desired research output.

Because the engine reasons from visible geometry, the same core can support
marketplaces, catalogs, directories, dashboards, documentation sites, and
other web interfaces.

## Human-like pacing

Pacing should be conservative and observable:

- one action at a time;
- wait for the resulting frame before planning the next action;
- use natural pauses appropriate to page latency;
- stop on errors, denials, challenges, or unexpected state;
- cap pages, records, and session duration;
- avoid concurrency and background request bursts.

This reproduces important timing characteristics of ordinary navigation. It
is not a promise of undetectability and must never be used to defeat a
platform's controls.

## Compliance gates

Before every run, establish:

1. the operator is authorized to access and automate the target;
2. the intended data may lawfully be collected and retained;
3. the workflow complies with applicable terms and published rules;
4. no CAPTCHA, login, paywall, or access control will be bypassed;
5. consequential actions require explicit human approval;
6. screenshots and output have an appropriate retention policy.

On CAPTCHA, login, rate limit, denial, or consent prompts, stop or hand control
to an authorized human.

## Reliability rules

- Match text with normalization and confidence thresholds.
- Prefer spatial relationships over a single OCR label.
- Confirm the target is inside the current viewport.
- Use `cursor/plan` before `cursor/move`.
- Require a new screenshot after every action.
- Verify the resulting page state, not just pointer position.
- Keep evidence sufficient to explain every extracted field.
- Treat OCR and unlabeled-symbol classification as probabilistic.
