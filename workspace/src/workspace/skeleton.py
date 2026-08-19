"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: hold the standard project layout as DATA, in one place, so no
department ever computes a path.

Design doc v2.2 Section 16.1 is the authority for this shape. Everything else
in the package reads these tables — a layout expressed as code paths would be a
second place to be right about, and there is only ever one.

Version: 0.1.0
"""

from __future__ import annotations

# property name -> path relative to the project root.
DIRECTORIES: dict[str, str] = {
    "intent_dir": "intent",
    "architecture_dir": "architecture",
    "packets_dir": "packets",
    "ledger_dir": "ledger",
    "tickets_dir": "ledger/tickets",
    "state_dir": "state",
    "src_dir": "src",
}

FILES: dict[str, str] = {
    "project_toml_path": "project.toml",
    "dictionary_path": "dictionary.toml",
    "registry_path": "registry.toml",
    "build_log_path": "ledger/build-log.md",
    "rulings_path": "ledger/rulings.md",
    "meter_path": "ledger/meter.jsonl",
    "evidence_path": "ledger/evidence.md",
}

# What open_project demands. A typed path is handed out for every entry above,
# but only these must EXIST — the rest are addresses departments write to when
# they have something to say. registry.toml is pointedly absent: its absence is
# the design (inherit the global), never a fault.
REQUIRED_DIRECTORIES: tuple[str, ...] = tuple(DIRECTORIES.values())
REQUIRED_FILES: tuple[str, ...] = ("project.toml",)

# Written at birth, with their seed content. project.toml and build-log.md are
# filled in by the factory (they carry identity and a timestamp); the rest are
# stamped as-is so every Dictionary path is a real file from the first moment.
#
# registry.toml is POINTEDLY ABSENT and must stay that way: its absence is what
# means "inherit the global brains" (design doc 16.2 rule 2, R-012). Creating an
# empty one would silently override the global with nothing.
BIRTH_FILE_CONTENT: dict[str, str] = {
    "dictionary.toml": (
        "# The project's Dictionary — names, styles, mappings.\n"
        "# Written by Cortex; empty until the architecture exists.\n"
    ),
    "ledger/rulings.md": "# Rulings\n\nProject-scoped rulings, append-only.\n",
    "ledger/evidence.md": (
        "# Evidence\n\nObserved truths, append-only. What was measured, not "
        "what was assumed.\n"
    ),
    "ledger/meter.jsonl": "",  # JSONL: one receipt per line, so it starts empty
}

NEVER_CREATED: tuple[str, ...] = ("registry.toml",)

GITKEEP = ".gitkeep"

# The lifecycle, in declared order (design doc 16.2 rule 4).
STATUSES: tuple[str, ...] = (
    "draft",
    "intent_signed",
    "building",
    "adversarial",
    "deployed",
    "live",
    "amended",
)

DRAFT = "draft"

# Permitted transitions as an explicit map rather than an index comparison.
# The long-haul loop (Section 13) makes the order non-linear: `live` folds back
# through `amended` into `building`, so "the next one along" is not a rule that
# can express this. A map can, and it also makes `amended -> deployed` illegal
# by simply not being here.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("intent_signed",),
    "intent_signed": ("building",),
    "building": ("adversarial",),
    "adversarial": ("deployed",),
    "deployed": ("live",),
    "live": ("amended",),
    "amended": ("building",),
}

# Only this transition is gate-checked today. The rest validate order and
# nothing else: enforcement arrives with each department, not before it
# (design doc 16.2 rule 4 — structure now, gates as they are earned).
SIGNATURE_REQUIRED: tuple[tuple[str, str], ...] = (("draft", "intent_signed"),)
