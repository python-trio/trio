"""Transform references to typevars to avoid missing reference errors.

See https://github.com/sphinx-doc/sphinx/issues/7722 also.
"""
from __future__ import annotations

import re

from pathlib import Path

from sphinx.addnodes import pending_xref, Element
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment
from sphinx.errors import NoUri


def identify_typevars() -> None:
    """Record all typevars in trio."""
    trio_folder = Path(__file__, "..", "..", "..", "trio").resolve()
    print(trio_folder)
    for filename in trio_folder.rglob("*.py"):
        with open(filename, encoding="utf8") as f:
            for line in f:
                # A simple regex should be sufficient to find them all, no need to actually parse.
                match = re.search(
                    r"^\s*(\w+)\s*=\s*(TypeVar|TypeVarTuple|ParamSpec)\(",
                    line,
                )
                if match is not None:
                    relative = "trio" / filename.relative_to(trio_folder)
                    relative = relative.with_suffix("")
                    if relative.name == "__init__":  # Package, remove.
                        relative = relative.parent
                    kind = match.group(2)
                    name = match.group(1)
                    typevars_qualified[f'{".".join(relative.parts)}.{name}'] = kind
                    existing = typevars_named.setdefault(name, kind)
                    if existing != kind:
                        print("Mismatch: {} = {}, {}", name, existing, kind)


# All our typevars, so we can suppress reference errors for them.
typevars_qualified = {
    "_os.PathLike": "typing.TypeVar",
}
typevars_named = {}
identify_typevars()

print("Typevars: ", sorted(typevars_qualified))


def lookup_reference(
    app: Sphinx,
    env: BuildEnvironment,
    node: pending_xref,
    contnode: Element,
) -> Element | None:
    """Handle missing references."""
    # If this is a typing_extensions object, redirect to typing.
    # Most things there are backports, so the stdlib docs should have an entry.
    target: str = node["reftarget"]
    if target.startswith("typing_extensions."):
        new_node = node.copy()
        new_node["reftarget"] = f"typing.{target[18:]}"
        return app.emit_firstresult(
            "missing-reference",
            env,
            new_node,
            contnode,
            allowed_exceptions=(NoUri,),
        )

    try:
        typevar_type = typevars_qualified[target]
    except KeyError:
        # Imports might mean the typevar was defined in a different module or something.
        # Fall back to checking just by name.
        dot = target.rfind(".")
        stem = target[dot + 1 :] if dot >= 0 else target
        try:
            typevar_type = typevars_qualified[stem]
        except KeyError:
            return None

    new_node = node.copy()
    new_node["reftarget"] = f"typing.{typevar_type}"
    new_node = app.emit_firstresult(
        "missing-reference",
        env,
        new_node,
        contnode,
        allowed_exceptions=(NoUri,),
    )
    reftitle = new_node["reftitle"]
    # Is normally "(in Python 3.XX)", make it say typevar/paramspec/etc
    paren = "(" if reftitle.startswith("(") else ""
    new_node["reftitle"] = f"{paren}{typevar_type}, {reftitle.lstrip('(')}"
    new_node["classes"].append("typevarref")
    return new_node


def setup(app):
    app.connect("missing-reference", lookup_reference, -10)
