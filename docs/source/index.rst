.. Trio documentation master file, created by
   sphinx-quickstart on Sat Jan 21 19:11:14 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

===================================================
Trio: async programming for humans and snake people
===================================================

Trio is an experimental attempt to produce a production-quality,
`permissively licensed
<https://github.com/python-trio/trio/blob/master/LICENSE>`__,
async/await-native I/O library for Python, with an emphasis on
**usability** and **correctness** – we want to make it *easy* to get
things *right*. Our ultimate goal is to become Python's de facto
standard async I/O library.

This is project is young and still somewhat experimental: the overall
design is solid and the existing features are fully tested and
documented, but you may encounter missing functionality or rough
edges. We *do* encourage you do use it, but you should `read and
subscribe to this issue
<https://github.com/python-trio/trio/issues/1>`__ to get warning and a
chance to give feedback about any compatibility-breaking changes.

Vital statistics:

* Supported environments: Linux, MacOS, or Windows running some kind of Python
  3.5-or-better (either CPython or PyPy3 is fine). \*BSD and illumus likely
  work too, but are untested.

* Install: ``python3 -m pip install -U trio`` (or on Windows, maybe
  ``py -3 -m pip install -U trio``). No compiler needed.

* Tutorial and reference manual: https://trio.readthedocs.io

* Bug tracker and source code: https://github.com/python-trio/trio

* License: MIT or Apache 2, your choice

* Code of conduct: Contributors are requested to follow our `code of
  conduct
  <https://github.com/python-trio/trio/blob/master/CODE_OF_CONDUCT.md>`_
  in all project spaces.


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   tutorial.rst
   reference-core.rst
   reference-io.rst
   reference-testing.rst
   reference-hazmat.rst
   design.rst
   history.rst

====================
 Indices and tables
====================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
