# The apport_python_hook package is only installed as part of Ubuntu's system
# python, and not available in venvs. So before we can import it we have to
# make sure it's on sys.path.
import sys

import _common  # isort: split

sys.path.append("/usr/lib/python3/dist-packages")
import apport_python_hook

apport_python_hook.install()

from trio._core._multierror import MultiError  # Bypass deprecation warnings

raise MultiError([KeyError("key_error"), ValueError("value_error")])
