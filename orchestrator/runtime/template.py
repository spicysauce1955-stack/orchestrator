"""Runtime prompt templating (spec §4 typed I/O). Syntax: {{ ... }}.

Resolves {{name}} (pipeline input), {{step.output}} (prior step text), and
{{step.output.field}} (field of a prior step's structured output_data).
Prose containing angle brackets (List<T>) is never a reference.
"""

from __future__ import annotations

import re

from orchestrator.runtime.state import Artifact

_REF = re.compile(r"\{\{\s*([a-zA-Z_][\w.-]*)\s*\}\}")


class TemplateError(Exception):
    """Raised when a {{ ... }} reference cannot be resolved."""


def render_template(
    template: str, inputs: dict[str, str], artifacts: dict[str, Artifact]
) -> str:
    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        parts = token.split(".")
        head = parts[0]

        if len(parts) == 1:
            if head not in inputs:
                raise TemplateError(f"reference {{{{{token}}}}} matches no pipeline input")
            return inputs[head]

        if head not in artifacts:
            raise TemplateError(f"reference {{{{{token}}}}} targets unknown step '{head}'")
        if parts[1] != "output":
            raise TemplateError(
                f"reference {{{{{token}}}}} must use '.output' (got '.{parts[1]}')"
            )
        artifact = artifacts[head]
        if len(parts) == 2:
            return artifact.output
        if len(parts) == 3:
            data = artifact.output_data or {}
            if parts[2] not in data:
                raise TemplateError(
                    f"reference {{{{{token}}}}} field '{parts[2]}' not in output of '{head}'"
                )
            return str(data[parts[2]])
        raise TemplateError(f"reference {{{{{token}}}}} is too deeply nested (max 3 segments)")

    return _REF.sub(_sub, template)
