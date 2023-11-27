# The apport_python_hook package is only installed as part of Ubuntu's system
# python, and not available in venvs. So before we can import it we have to
# make sure it's on sys.path.
import sys

import _common  # isort: split

sys.path.append("/usr/lib/python3/dist-packages")
import apport_python_hook

apport_python_hook.install()

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

raise ExceptionGroup("", [KeyError("key_error"), ValueError("value_error")])
