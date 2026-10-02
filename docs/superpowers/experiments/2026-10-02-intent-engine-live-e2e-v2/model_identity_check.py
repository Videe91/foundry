"""Metadata-only identity check (no generation): does each exact model id exist, aliased?"""

import json
import os

out = {}
try:
    from xai_sdk import Client

    c = Client(api_key=os.environ["XAI_API_KEY"])
    m = c.models.get_language_model("grok-4.6")
    out["xai"] = {
        "requested": "grok-4.6",
        "name": getattr(m, "name", None),
        "aliases": list(getattr(m, "aliases", []) or []),
        "version": getattr(m, "version", None),
    }
except Exception as e:
    out["xai"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
try:
    import openai

    m = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"]).models.retrieve("gpt-6-astra")
    out["openai"] = {
        "requested": "gpt-6-astra",
        "id": m.id,
        "owned_by": getattr(m, "owned_by", None),
    }
except Exception as e:
    out["openai"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
try:
    import anthropic

    m = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]).models.retrieve(
        "claude-opus-5-5"
    )
    out["anthropic"] = {
        "requested": "claude-opus-5-5",
        "id": m.id,
        "display_name": getattr(m, "display_name", None),
    }
except Exception as e:
    out["anthropic"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
print(json.dumps(out, indent=2))
