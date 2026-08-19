"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: test open_project — that it validates rather than repairs, names
exactly what is missing, resolves the workspace root in the declared order, and
layers the registry.

Version: 0.1.0
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workspace import WorkspaceError, create_project, open_project, workspace_root
from workspace.factory import WORKSPACE_ROOT_ENV
from workspace.skeleton import DIRECTORIES, FILES, NEVER_CREATED

SLUG = "demo-app"
NAME = "Demo App"


def test_create_then_open_gives_the_same_surface(tmp_path: Path) -> None:
    made = create_project(SLUG, NAME, root=tmp_path)
    opened = open_project(SLUG, root=tmp_path)

    assert (opened.slug, opened.name, opened.id) == (made.slug, made.name, made.id)
    assert (opened.status, opened.created) == (made.status, made.created)
    assert opened.root_dir == made.root_dir
    for prop in (*DIRECTORIES, *FILES):
        assert getattr(opened, prop) == getattr(made, prop), prop


def test_a_project_can_be_opened_by_path(tmp_path: Path) -> None:
    made = create_project(SLUG, NAME, root=tmp_path)
    assert open_project(made.root_dir).slug == SLUG


def test_opening_something_that_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        open_project("no-such-project", root=tmp_path)
    assert "does not exist" in str(excinfo.value)


@pytest.mark.parametrize(
    "relative", ["project.toml", "ledger", "packets", "state", "src", "intent",
                 "architecture", "ledger/tickets"]
)
def test_each_missing_piece_is_named(tmp_path: Path, relative: str) -> None:
    """Never repairs silently — a broken workspace is a finding, not a fix-up."""
    import shutil

    project = create_project(SLUG, NAME, root=tmp_path)
    target = project.root_dir / relative
    shutil.rmtree(target) if target.is_dir() else target.unlink()

    with pytest.raises(WorkspaceError) as excinfo:
        open_project(SLUG, root=tmp_path)
    assert relative in str(excinfo.value)
    assert target.exists() is False, "open_project repaired the workspace"


def test_a_missing_optional_file_is_not_an_error(tmp_path: Path) -> None:
    """Discriminating: if everything were required, the parametrised test above
    would pass for the wrong reason. registry.toml is absent by design and
    dictionary.toml is an address departments fill in later."""
    project = create_project(SLUG, NAME, root=tmp_path)
    project.dictionary_path.unlink()
    assert open_project(SLUG, root=tmp_path).slug == SLUG


def test_unparseable_project_toml_is_named(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    project.project_toml_path.write_text("this is not = = toml", encoding="utf-8")
    with pytest.raises(WorkspaceError) as excinfo:
        open_project(SLUG, root=tmp_path)
    assert "not parseable" in str(excinfo.value)


@pytest.mark.parametrize("key", ["id", "slug", "name", "created", "status"])
def test_a_missing_project_toml_key_is_named(tmp_path: Path, key: str) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    kept = [
        line
        for line in project.project_toml_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(f"{key} =")
    ]
    project.project_toml_path.write_text("\n".join(kept), encoding="utf-8")

    with pytest.raises(WorkspaceError) as excinfo:
        open_project(SLUG, root=tmp_path)
    assert f"'{key}'" in str(excinfo.value)


def test_an_unknown_status_is_rejected(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    text = project.project_toml_path.read_text(encoding="utf-8")
    project.project_toml_path.write_text(
        text.replace('status = "draft"', 'status = "shipped"'), encoding="utf-8"
    )
    with pytest.raises(WorkspaceError) as excinfo:
        open_project(SLUG, root=tmp_path)
    assert "unknown status" in str(excinfo.value)


# --- root resolution: explicit beats env beats default ---------------------


def test_explicit_root_beats_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(tmp_path / "from-env"))
    explicit = tmp_path / "explicit"
    assert workspace_root(explicit) == explicit


def test_the_environment_beats_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from_env = tmp_path / "from-env"
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(from_env))
    assert workspace_root() == from_env


def test_the_default_is_projects_under_the_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    root = workspace_root()
    assert root.name == "projects"
    assert (root.parent / "workspace" / "src" / "workspace").is_dir()


def test_an_unlocatable_repo_demands_the_env_var_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never guess into a random directory — a project is a folder, and
    stamping one somewhere unexpected is a mess nobody can see."""
    import workspace.factory as factory

    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    monkeypatch.setattr(factory, "_repo_root", lambda: None)
    with pytest.raises(WorkspaceError) as excinfo:
        factory.workspace_root()
    assert WORKSPACE_ROOT_ENV in str(excinfo.value)


def test_only_one_environment_variable_is_ever_read() -> None:
    """R-013 analogue, asserted structurally rather than by grepping text.

    Every environment access in the package is located in the AST and its key
    checked. A string search would be fooled by a docstring — and by a variable
    holding the name of a different variable, which is exactly the sort of thing
    a guard should not be fooled by.
    """
    import ast
    import inspect

    import workspace.factory as factory
    import workspace.project as project_module
    import workspace.skeleton as skeleton

    accesses: list[tuple[str, str]] = []
    for module in (factory, project_module, skeleton):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            # os.environ["X"] / os.environ.get("X") / os.getenv("X")
            key = None
            if isinstance(node, ast.Subscript) and _is_environ(node.value):
                key = _literal(node.slice)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "get" and \
                        _is_environ(func.value):
                    key = _literal(node.args[0]) if node.args else "<dynamic>"
                elif isinstance(func, ast.Attribute) and func.attr == "getenv":
                    key = _literal(node.args[0]) if node.args else "<dynamic>"
            if key is not None:
                accesses.append((module.__name__, key))

    assert accesses, "no environment access found — the guard is not reaching"
    for module_name, key in accesses:
        assert key == "WORKSPACE_ROOT_ENV", (
            f"{module_name} reads an environment variable other than "
            f"FOUNDRY_WORKSPACE_ROOT: {key}"
        )


def _is_environ(node: object) -> bool:
    import ast

    return isinstance(node, ast.Attribute) and node.attr == "environ"


def _literal(node: object) -> str:
    import ast

    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name):
        return node.id
    return "<dynamic>"


# --- registry layering ------------------------------------------------------


def test_absent_project_registry_falls_back_to_the_global(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    global_registry = tmp_path / "global-registry.toml"
    global_registry.write_text("", encoding="utf-8")
    assert project.effective_registry_path(global_registry) == global_registry


def test_a_present_project_registry_wins(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    project.registry_path.write_text("", encoding="utf-8")
    global_registry = tmp_path / "global-registry.toml"
    global_registry.write_text("", encoding="utf-8")
    assert project.effective_registry_path(global_registry) == project.registry_path


def test_no_registry_anywhere_is_an_error_not_a_guess(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    with pytest.raises(WorkspaceError) as excinfo:
        project.effective_registry_path(None)
    assert "no registry.toml" in str(excinfo.value)


def test_layering_resolves_which_file_never_its_contents(tmp_path: Path) -> None:
    """R-012: the Workspace decides WHICH registry, never what is in it."""
    project = create_project(SLUG, NAME, root=tmp_path)
    project.registry_path.write_text("nonsense = [", encoding="utf-8")
    assert project.effective_registry_path(tmp_path / "g.toml") == project.registry_path
