# Packet P-006 — Attachments: Text Kind (.md / .txt)

**Department:** Coding Floor
**Wave:** 5 (builds on P-005; Anthropic family stamped and live-proven)
**Language:** Python 3.12
**Supersedes:** the earlier P-006 "OpenAI Family" draft, which was never built. Delete that packet file if present; the OpenAI family re-issues as P-007 after this packet stamps. Record the supersession in the build log.

**Architecture context:** Intent — the next department — consumes what users bring, and users bring `.md` and `.txt` files (specs, notes, READMEs) more often than PDFs. Per the current Anthropic API reference (checked 2026-08-18): plain text is a native document type (`text/plain`); markdown has no distinct media type and lands as plain text. Building this now, family-agnostically, avoids renovating every adapter later.

## One job

`Attachment` gains a third kind, `"text"`, covering `.md` and `.txt` — loaded with the same rules as image/pdf and sent as a `text/plain` document part — proven live by the smoke attachments demo naming all three file types.

## Dictionary changes

- `Attachment.kind` allowed values become: `"image"`, `"pdf"`, `"text"`.
- Extension map for `"text"`: `.md`, `.txt` → media type `text/plain`.
- No other names change.

## Files to create or modify (each under 300 lines)

```
switchboard/
├── smoke.py / smoke_fixtures.py — MODIFY: tiny .md fixture ("# Foundry test\nP-006");
│                                   attachments demo sends all three and asks the model
│                                   to name all THREE file types
├── src/switchboard/
│   ├── request.py          — MODIFY under R-016 (see below): widen the kind literal
│   └── adapters.py         — MODIFY: AnthropicAdapter handles kind="text"
└── tests/
    ├── test_adapters.py    — MODIFY: text-kind tests
    └── test_smoke.py       — MODIFY: wiring guard covers the third kind (guard move to
                               test_smoke_wiring.py only if the 300 ceiling forces it —
                               that pre-authorization stands from R-018's extension)
```

**R-016 flag, declared upfront:** `request.py` is stamped; widening `Attachment.kind` is impossible without touching it. This is a one-amendment unstamping of exactly that file; it re-stamps on cold-verified green.

All other files stamped and untouched.

## Pinned dependencies

None added.

## Behaviour contract

1. **Loading rules identical to image/pdf:** read bytes from `path`, base64-encode, no processing libraries. Missing file → `FileNotFoundError` naming the path. An extension outside the text map (e.g. `.rst`, `.doc`) for `kind="text"` → `ValueError` naming the extension.
2. **AnthropicAdapter:** `kind="text"` becomes a file/document content part with a base64 `data:text/plain` data URL — the same LiteLLM file-part shape the PDF path uses, media type swapped. Appended to the last user message alongside any other attachment parts, same ordering rules.
3. **No adapter, with a text attachment:** existing behaviour holds — `ProviderCallError` stating attachments are unsupported for that family. Never silently dropped.
4. **Base64 hygiene:** the encoded payload must contain no newlines (the API reference requires newline-free base64). This already holds if standard b64encode is used — assert it in a test rather than assume it.
5. **Smoke — attachments demo:** now sends PNG + PDF + the .md fixture in one call and asks the model to name all three file types it received. Expected (reported, not asserted): the reply names an image, a PDF, and a text/markdown document.
6. **Wiring guard:** gains one assertion — a text attachment part reaches the outgoing call.

## Rulings to record (append to ledger/rulings.md)

- **R-021:** "Citations and the Files API are deferred until a consuming department exists — citations pair with the first department needing sourced answers (likely Intent's research slot or the judges); the Files API pairs with repeated-document workflows (Intent holding a user's spec across a conversation). No renovation without a work order."

## Tests that must pass (ALL offline)

test_adapters.py additions:
- text attachment (.md written to tmp_path) → a text/plain base64 file part on the last user message
- .txt accepted identically; .rst for kind="text" → ValueError naming ".rst"
- missing text file → FileNotFoundError naming the path
- encoded payload contains no newline characters
- mixed call (image + pdf + text) → all three parts present, on the last user message, order preserved

test_smoke.py / wiring guard:
- attachments demo sends three parts; the third is text/plain (assert via fakes)

Full suite green.

## Forbidden

- No changes to stamped files beyond request.py (flagged above) and the listed scope.
- No new dependencies, no processing libraries, no keys, no network in tests.
- No citations, no Files API, no OpenAI family work — P-007 and later.
