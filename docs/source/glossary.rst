:orphan:

.. _glossary:

********
Glossary
********

.. glossary::

   asynchronous file object
       This is an object with an API identical to a :term:`file object`, with
       the exception that all methods that do I/O are async functions.

       The main ways to create an asynchronous file object are by using the
       :func:`trio.open_file` function or the :meth:`trio.Path.open`
       method. See :ref:`async-file-io` for more details.
