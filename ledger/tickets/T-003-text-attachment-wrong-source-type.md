# T-003 — P-006's text part uses a source shape Anthropic rejects

**From:** Live run 2026-08-18, prove-3 (attachments)
**Raised by:** Coding Floor
**Status:** RESOLVED — option (a) ruled by the packet author; fix applied.
**Severity proposed:** S1 (a shipped kind cannot make a live call)

## Symptom

`python smoke.py` completes PING, PROVE 1, and PROVE 2, then dies in PROVE 3:

```
ProviderCallError: all models failed for role 'floor_agent':
tried anthropic/claude-haiku-4-5-20251001, anthropic/claude-sonnet-5;
last error: litellm.BadRequestError - AnthropicException
messages.0.content.3.document.source.base64.media_type:
  Input should be 'application/pdf'
```

`content.3` is the text part — index 0 is the prompt, 1 the image, 2 the PDF.
**The image and PDF parts are fine; only the new text kind fails.** The
fallback chain worked correctly: both models rejected the same malformed
payload, which is a request defect rather than a provider outage.

## Root cause — the packet's contract is wrong against the real API

P-006 contract 2 specifies the text part as "a file/document content part with
a base64 `data:text/plain` data URL — the same LiteLLM file-part shape the PDF
path uses, media type swapped." **That shape cannot work.** Anthropic's
`document` block accepts `source.type: "base64"` only with
`media_type: "application/pdf"`. Plain-text documents use a *different source
type* carrying **raw text, not base64**.

Reproduced offline through LiteLLM's real `AnthropicConfig.transform_request`,
no spend. Our current output:

```json
{"type": "document",
 "source": {"type": "base64", "media_type": "text/plain",
            "data": "IyBGb3VuZHJ5IHRlc3QKUC0wMDY="}}
```

That is exactly what the API rejects. The media type cannot simply be
"swapped": the PDF path's shape is base64-only by construction.

## Verified fix (offline, not applied)

A native Anthropic document block with `source.type: "text"` and raw content
passes LiteLLM's transformation unchanged and matches the documented API shape:

```json
{"type": "document",
 "source": {"type": "text", "media_type": "text/plain",
            "data": "# Foundry test\nP-006"}}
```

Verified on the full mixed call (image + PDF + text). Resulting document
sources: `[('base64', 'application/pdf'), ('text', 'text/plain')]` — no
violating base64 document source. Two rejected alternatives, for the record: a
non-base64 `data:text/plain,` file part is rejected by **LiteLLM itself**
("Image url not in expected format"); a plain `text` content part transforms
cleanly but discards document semantics (no filename, and it forecloses
citations under R-021).

## Why this needs a ruling rather than a floor fix

The correction changes P-006's stated behaviour contract, so it is not the
floor's to make (Law rule 2):

1. **Contract 2** — the text part is a native document block with
   `source.type: "text"`, *not* the PDF file-part shape with a swapped media
   type.
2. **Contract 4 becomes moot for this kind** — the correct shape carries raw
   text, so there is no base64 payload whose newline-freedom can be asserted.
   Base64 hygiene still applies to image and PDF.
3. **Three specified tests change** — the ones asserting
   `data:text/plain;base64,`, the base64 round-trip, and the no-newline
   property. The `.rst` → `ValueError` and missing-file → `FileNotFoundError`
   tests remain valid as written, as does extension validation.

## The deeper defect — R-019 was violated in spirit, third occurrence

The offline suite was green while the live call was malformed, because the
tests asserted **our implementation's shape** (`data:text/plain;base64,`)
rather than the API's. R-019 says fakes model the API, never the
implementation — and the fake here encoded the packet's assumption. This is the
third instance of the same class this session: `load_env` (nothing exercised
`main()`), `include_usage` (usage read from a shape the API does not send
without it), and now this.

**The transformation check that found this in minutes is the same one that
refuted H1 in T-002, and it costs nothing.** Recommended standing rule: any
packet introducing or changing a provider payload shape must run that shape
through the provider's real transformation offline before the suite is called
green. Proposed as a ruling in its own right.

## Question for Cortex

- **(a)** Amend P-006 contract 2 to the verified document/`source.type: "text"`
  shape, drop contract 4 for the text kind, and update the three affected
  tests. Preferred — the fix is verified and the change is small.
- **(b)** Withdraw the text kind pending a redesign.
- **(c)** Something else.

---

## RESOLVED — option (a), ruled by the packet author

Cortex ruled option (a) and recorded **R-022**. Applied as a single amendment:

1. **Contract 2 amended.** Text attachments are a native Anthropic document
   block with `source.type: "text"` carrying raw content — not the PDF
   file-part shape with a swapped media type, which the API rejects.
2. **Contract 4 void for the text kind only.** There is no base64 payload to
   keep newline-free. The assertion still binds for pdf and image, and the test
   was rewritten to cover those two rather than deleted.
3. **The three invalidated tests rewritten** to the transformation-verified
   shape, each citing that verification as its observation source per R-019.
   The `.rst` → `ValueError` and missing-file → `FileNotFoundError` tests are
   unchanged, as ruled.
4. **R-022 enforced in the suite.** `test_adapters.py` now runs the adapter's
   real output through LiteLLM's real `AnthropicConfig.transform_request`, so a
   payload the provider would reject fails offline instead of on a smoke run.

**Full suite: 108 passed, 0 failed.** The packet's contract 2 was the defect;
the build was faithful to it. **CLOSED.**
