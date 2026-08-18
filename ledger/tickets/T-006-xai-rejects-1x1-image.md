# T-006 — xAI rejects the 1x1 PNG fixture; three families had accepted it

**From:** Live run 2026-08-18, PROVE 3 on the xai family
**Raised by:** Coding Floor
**Status:** FIXED, awaiting live confirmation
**Severity proposed:** S2 (a shared fixture, not a shipped shape — the adapter
is correct and no product code was wrong)

## Symptom

Every phase passed through the xai cache demo. The refusal note printed exactly
as designed — `note: this family does not accept pdf — sending image, text` —
and then the call died:

```
XaiException - {"code":"invalid_image",
"error":"Image dimensions 1x1 are too small.
Both width and height must be at least 8 pixels."}
```

## Diagnosis

The fault is in `smoke_fixtures.TINY_PNG_BASE64`, which was a **1x1 pixel**
PNG, 70 bytes. Confirmed by decoding the IHDR chunk offline.

**The adapter and the payload shape are correct.** The image part reached xAI
in the transformation-verified form P-009 built and was parsed successfully
enough for xAI to read its dimensions and object to them. This is a content
defect in the test image, not a translation defect.

## Why nothing caught it

Anthropic, OpenAI, and Gemini all accepted a single pixel across five live
runs, so a 1x1 fixture looked settled. xAI is the first family to state a
minimum image dimension. No offline check could have found this: the R-022
transformation checks assert byte fidelity of the base64 payload, and a 1x1
PNG round-trips as faithfully as any other. This is R-024 again, in a place we
had not looked — **fidelity is not acceptance, and acceptance criteria include
the content of the attachment, not only its shape.**

The registered pattern from T-003/T-004 was about *which part type* a family
accepts. T-006 adds a second axis: a family may accept the part type and still
reject what is inside it.

## Fix applied

`TINY_PNG_BASE64` is now a **16x16** 8-bit greyscale checker, 82 bytes, still
built with no image library. 16 rather than 8 to leave margin above the only
stated minimum. A shared fixture must satisfy the strictest family.

A regression guard in `test_smoke.py` decodes the fixture's IHDR and asserts
both dimensions are at least 8 — **demonstrated discriminating**: the retired
1x1 constant is checked in the same test and fails the same assertion, so the
guard cannot pass vacuously.

The 1x1 constants inside the offline adapter tests are deliberately left alone.
They never reach a provider and their job is byte-fidelity, which a single
pixel proves as well as any other image.

## For Cortex

Standing-note candidate: **attachment fixtures are provider-facing payloads and
must satisfy the strictest family's content rules, not merely the loosest.**
Known minimum so far: xAI, 8x8 pixels. No other family states one.
