"""End-to-end Intent Engine validation (Intent Engine runtime reset, offline harness).

A held-out project evolves through realistic changes; only the final outcome is scored
(``outcome``). ``scenario`` is what executors may see; ``expectations`` never reaches them.
Nothing here is wired to a live model: a live run is a separate, later decision.
"""
