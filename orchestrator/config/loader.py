"""Load and cross-validate a .orchestrator/ workspace (spec §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from orchestrator.config.schemas import (
    Config,
    CoreKnowledge,
    KnowledgeSource,
    Pipeline,
    Role,
    Skill,
)


class ConfigError(Exception):
    """Raised when a workspace is malformed or has dangling references."""


@dataclass
class Workspace:
    config: Config
    roles: dict[str, Role] = field(default_factory=dict)
    skills: dict[str, Skill] = field(default_factory=dict)
    core_knowledge: CoreKnowledge | None = None
    knowledge_sources: dict[str, KnowledgeSource] = field(default_factory=dict)
    pipelines: dict[str, Pipeline] = field(default_factory=dict)

    def knowledge_names(self) -> set[str]:
        names = set(self.knowledge_sources)
        if self.core_knowledge is not None:
            names.add("core")
        return names


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - exercised via malformed yaml
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at top level")
    return data


def _load_dir(base: Path, subdir: str, model, into: dict) -> None:
    directory = base / subdir
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.yaml")):
        name = path.stem
        try:
            obj = model.model_validate({**_read_yaml(path), "name": name})
        except Exception as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        into[name] = obj


def load_workspace(base: Path) -> Workspace:
    base = Path(base)
    if not base.is_dir():
        raise ConfigError(f"{base}: workspace directory not found")

    config_path = base / "config.yaml"
    config = Config.model_validate(_read_yaml(config_path)) if config_path.is_file() else Config()
    ws = Workspace(config=config)

    _load_dir(base, "roles", Role, ws.roles)
    _load_dir(base, "skills", Skill, ws.skills)
    _load_dir(base, "pipelines", Pipeline, ws.pipelines)

    knowledge_dir = base / "knowledge"
    if knowledge_dir.is_dir():
        for path in sorted(knowledge_dir.glob("*.yaml")):
            if path.stem == "core":
                ws.core_knowledge = CoreKnowledge.model_validate(_read_yaml(path))
            else:
                ws.knowledge_sources[path.stem] = KnowledgeSource.model_validate(
                    {**_read_yaml(path), "name": path.stem}
                )

    _resolve_references(ws)
    return ws


def _resolve_references(ws: Workspace) -> None:
    errors: list[str] = []
    known_knowledge = ws.knowledge_names()

    for role in ws.roles.values():
        for skill in role.skills:
            if skill not in ws.skills:
                errors.append(f"role '{role.name}' references unknown skill '{skill}'")
        for source in role.knowledge:
            if source not in known_knowledge:
                errors.append(f"role '{role.name}' references unknown knowledge '{source}'")
        if role.access is not None and role.access.knowledge is not None:
            ka = role.access.knowledge
            for source in (*ka.read, *ka.write):
                if source not in known_knowledge:
                    errors.append(
                        f"role '{role.name}' access.knowledge references unknown "
                        f"source '{source}'"
                    )

    for skill in ws.skills.values():
        for source in skill.knowledge:
            if source not in known_knowledge:
                errors.append(f"skill '{skill.name}' references unknown knowledge '{source}'")

    for pipeline in ws.pipelines.values():
        for step in pipeline.steps:
            if step.role is not None and step.role not in ws.roles:
                errors.append(
                    f"pipeline '{pipeline.name}' step '{step.id}' references unknown role "
                    f"'{step.role}'"
                )

    if errors:
        raise ConfigError("; ".join(errors))
