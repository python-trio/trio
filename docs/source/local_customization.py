from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.domains.python import PyClasslike
from sphinx.ext.autodoc import (
    FunctionDocumenter, MethodDocumenter, ClassLevelDocumenter, Options,
)

"""

.. interface:: The nursery interface

   .. attribute:: blahblah

"""

class Interface(PyClasslike):
    def handle_signature(self, sig, signode):
        signode += addnodes.desc_name(sig, sig)
        return sig, ""

    def get_index_text(self, modname, name_cls):
        return "{} (interface in {})".format(name_cls[0], modname)

def setup(app):
    app.add_directive_to_domain("py", "interface", Interface)
