.. Trio documentation master file, created by
   sphinx-quickstart on Sat Jan 21 19:11:14 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

=============================================================
Trio: a friendly Python library for async concurrency and I/O
=============================================================

The Trio project's goal is to produce a production-quality,
`permissively licensed
<https://github.com/python-trio/trio/blob/master/LICENSE>`__,
async/await-native I/O library for Python. Like all async libraries,
its main purpose is to help you write programs that do **multiple
things at the same time** with **parallelized I/O**. A web spider that
wants to fetch lots of pages in parallel, a web server that needs to
juggle lots of downloads and websocket connections at the same time, a
process supervisor monitoring multiple subprocesses... that sort of
thing. Compared to other libraries, Trio attempts to distinguish
itself with an obsessive focus on **usability** and
**correctness**. Concurrency is complicated; we try to make it *easy*
to get things *right*.

Trio was built from the ground up to take advantage of the `latest
Python features <https://www.python.org/dev/peps/pep-0492/>`__, and
draws inspiration from `many sources
<https://github.com/python-trio/trio/wiki/Reading-list>`__, in
particular Dave Beazley's `Curio <https://curio.readthedocs.io/>`__.
The resulting design is radically simpler than older competitors like
`asyncio <https://docs.python.org/3/library/asyncio.html>`__ and
`Twisted <https://twistedmatrix.com/>`__, yet just as capable. Trio is
the Python I/O library I always wanted; I find it makes building
I/O-oriented programs easier, less error-prone, and just plain more
fun. Perhaps you'll find the same.

This project is young and still somewhat experimental: the overall
design is solid and the existing features are fully tested and
documented, but you may encounter missing functionality or rough
edges. We *do* encourage you do use it, but you should `read and
subscribe to issue #1
<https://github.com/python-trio/trio/issues/1>`__ to get warning and a
chance to give feedback about any compatibility-breaking changes.

Vital statistics:

* Supported environments: We test on

  - Python: 3.6+ (CPython and PyPy)
  - Windows, macOS, Linux (glibc and musl), FreeBSD

  Other environments might also work; give it a try and see.

* Install: ``python3 -m pip install -U trio`` (or on Windows, maybe
  ``py -3 -m pip install -U trio``). No compiler needed.

* Tutorial and reference manual: https://trio.readthedocs.io

* Bug tracker and source code: https://github.com/python-trio/trio

* Real-time chat: https://gitter.im/python-trio/general

* Discussion forum: https://trio.discourse.group

* License: MIT or Apache 2, your choice

* Contributor guide: https://trio.readthedocs.io/en/latest/contributing.html

* Code of conduct: Contributors are requested to follow our `code of
  conduct
  <https://trio.readthedocs.io/en/latest/code-of-conduct.html>`_
  in all project spaces.


.. toctree::
   :maxdepth: 2
   :caption: Trio's friendly, yet comprehensive, manual:

   tutorial.rst
   awesome-trio-libraries.rst
   reference-core.rst
   reference-io.rst
   reference-testing.rst
   reference-lowlevel.rst
   design.rst
   history.rst
   contributing.rst
   releasing.rst
   code-of-conduct.rst

====================
 Indices and tables
====================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
* :ref:`glossary`
