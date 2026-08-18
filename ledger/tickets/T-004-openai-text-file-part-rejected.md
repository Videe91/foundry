# T-004 — OpenAI rejects the text/plain file part; R-022 could not have caught it

**From:** Live run 2026-08-18, PROVE 3 on the openai family
**Raised by:** Coding Floor
**Status:** RESOLVED by R-024 — candidate (b) applied, framed inline text part.
**Severity proposed:** S1 (a shipped kind cannot make a live call on one family)

## Symptom

Six of seven phases passed. PROVE 3 on the openai family died:

```
OpenAIException - Invalid file data: 'messages[0].content[3].file.file_data'.
Expected a base64-encoded data URL with an application/pdf MIME type
(e.g. 'data:application/pdf;base64,...'), but got unsupported MIME type 'text/plain'.
```

`content[3]` is the text attachment — index 0 the prompt, 1 the image, 2 the
PDF. **The image and PDF parts were accepted; only the text kind failed**, and
only on OpenAI. Anthropic's PROVE 3 in the same run named all three file types
correctly.

## Root cause

**OpenAI's file content part accepts `application/pdf` only.** A `text/plain`
data URL in `file.file_data` is rejected outright. Candidate (a) — the file
part with a text/plain data URL, chosen in P-007 — is therefore invalid for
this family, and candidate (b), the inline text part, is the surviving option.

## Why the R-022 check passed anyway — the finding that matters

**LiteLLM performs no MIME validation on file parts.** Its entire file-part
handling is:

```python
def _common_file_data_check(self, content_item):
    file_data = content_item.get("file_data")
    filename = content_item.get("filename")
    if file_data is not None and filename is None:
        content_item["filename"] = "my_file.pdf"
    return content_item
```

It injects a default filename and passes everything else through untouched. A
transformation that faithfully forwards an invalid payload **is behaving
correctly**, so the check reported green.

**R-022 verifies translation fidelity, not provider acceptance.** Those are
different properties, and the ruling's wording ("verify that shape through the
provider's real transformation code") reads as though they are the same. They
coincide only when the transformation validates — Anthropic's does (it is why
T-003's shape was catchable there in principle); OpenAI's does not.

This is not an argument against R-022. It caught the `my_file.pdf` filename
injection in this very packet, before ship. It is an argument that R-022 has a
stated ceiling, and that ceiling should be written into the ruling so a future
floor does not read a green transformation check as proof of acceptance.

## Same defect class as T-003 — twice now, on two providers

T-003: Anthropic's base64 **document** source is PDF-only; text uses
`source.type: "text"` with raw content. T-004: OpenAI's **file** part is
PDF-only; text goes inline. Two providers, one rule:

> **Document/file content parts are for PDFs. Text is carried as text.**

Worth booking as standing knowledge — it predicts the Gemini answer for P-008
before a single call is made, and it is the shape of question a docs-first pass
should ask explicitly.

## Verified fix (offline, not applied)

Candidate (b), the inline text part, involves no MIME negotiation at all:

```
text      'Name the three file types you received.'
image_url data:image/png;base64,...
file      data:application/pdf;base64,... filename=page.pdf
text      '# Foundry test\nP-006'
```

Non-pdf file parts remaining: **none**. Markdown content preserved verbatim:
**True**. This is the other candidate the packet named — not an invented third
shape.

## Questions for Cortex

1. **Apply candidate (b) for the OpenAI text kind?** The packet delegated the
   choice to a verification that could not settle it; (b) is the remaining
   named candidate and is verified.
2. **Bare text part, or labelled?** A bare inline part loses the filename the
   file part carried (`notes.md`). Prefixing something like
   `notes.md:\n<content>` would preserve it but is a rendering decision the
   floor must not make alone.
3. **Strengthen R-022?** Suggested amendment: a transformation check proves
   translation fidelity only. Where the provider constrains a payload beyond
   what the transformation validates, the packet must name the constraint and
   the fixture must assert it — or the shape is unproven until a live run.

---

## RESOLVED — candidate (b), ruled by the packet author

Recorded as **R-024**. Applied in one amendment:

1. **Candidate (b) built.** `OpenAIAdapter` carries `kind="text"` as an inline
   text part wrapped in a fixed mechanical frame — a filename line before the
   content and an end line after, chosen once as a module constant, pinned by
   test, never varied. The frame is the only signal separating an attached file
   from the user's own words, which the file part used to carry as `filename`.
2. **Extension validation kept.** `.rst` still raises `ValueError` naming it;
   the media type is simply never put on the wire.
3. **Tests cite the acceptance source.** The OpenAI text tests now name
   provider docs as the authority per R-024, since the transformation could not
   settle acceptance. The `no file part is ever non-pdf` assertion is kept as
   the standing T-004 regression guard, and R-022's filename-injection catch is
   preserved against the pdf kind, where it still applies.

**Full suite: 145 passed, 0 failed.** **CLOSED.**
