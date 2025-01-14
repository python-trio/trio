from __future__ import annotations

from typing import TYPE_CHECKING

from docutils.parsers.rst import directives as directives
from sphinx import addnodes
from sphinx.domains.python import PyClasslike
from sphinx.ext.autodoc import (
    ClassLevelDocumenter as ClassLevelDocumenter,
    FunctionDocumenter as FunctionDocumenter,
    MethodDocumenter as MethodDocumenter,
    Options as Options,
)

if TYPE_CHECKING:
    from sphinx.addnodes import desc_signature
    from sphinx.application import Sphinx

"""

.. interface:: The nursery interface

   .. attribute:: blahblah

"""


class Interface(PyClasslike):
    def handle_signature(self, sig: str, signode: desc_signature) -> tuple[str, str]:
        signode += addnodes.desc_name(sig, sig)
        return sig, ""

    def get_index_text(self, modname: str, name_cls: tuple[str, str]) -> str:
        return f"{name_cls[0]} (interface in {modname})"


def setup(app: Sphinx) -> None:
    app.add_directive_to_domain("py", "interface", Interface)
