"""Recipe/template library (spec §4.2): curated, versioned-with-the-package
pipeline recipes + the scaffolder behind `orch init` / `orch new --template`.

Each template is a data dir next to this file: `<name>/template.yaml` (manifest
with a one-line `description`) plus a complete `.orchestrator/` tree. The
integrity invariant — every shipped template scaffolds and compiles — is locked
by tests/unit/test_templates.py.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

_ROOT = Path(__file__).parent


class TemplateError(Exception):
    """Unknown template or a destination that already has a workspace."""


@dataclass(frozen=True)
class Template:
    name: str
    description: str
    path: Path


def list_templates() -> list[Template]:
    out: list[Template] = []
    for entry in sorted(_ROOT.iterdir()):
        manifest = entry / "template.yaml"
        if not manifest.is_file() or not (entry / ".orchestrator").is_dir():
            continue
        data = yaml.safe_load(manifest.read_text()) or {}
        out.append(
            Template(name=entry.name, description=str(data.get("description", "")), path=entry)
        )
    return out


def scaffold(name: str, dest: Path, *, force: bool = False) -> list[Path]:
    """Seed `dest/.orchestrator` from template `name`; returns created rel paths.

    `force=True` replaces an existing workspace wholesale (no merging — the
    result must stay identical to the vetted recipe).
    """
    by_name = {t.name: t for t in list_templates()}
    if name not in by_name:
        valid = ", ".join(sorted(by_name))
        raise TemplateError(f"unknown template '{name}' (valid: {valid})")
    target = dest / ".orchestrator"
    if target.exists():
        if not force:
            raise TemplateError(f"{target} already exists (use force to replace)")
        shutil.rmtree(target)
    src = by_name[name].path / ".orchestrator"
    shutil.copytree(src, target)
    return sorted(p.relative_to(dest) for p in target.rglob("*") if p.is_file())
