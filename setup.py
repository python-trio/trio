import inspect
import sys
from warnings import warn

from setuptools import setup

if len(inspect.stack()) == 1:
    warn(
        """
========================================
Unsupported building/installation method
========================================
This version of trio has dropped support for using `python setup.py ...`.
`setup.py` will be removed in future.
Please use `python -m build` (or any other PEP 517 build backend) and then install the built wheel with `pip` instead.
"""
    )

if __name__ == "__main__":
    setup()
