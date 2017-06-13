:orphan:

.. _glossary:

********
Glossary
********

.. glossary::

   asynchronous file object
       This is an object with an API identical to a :term:`file object`, with
       the exception that all non-computational methods are async functions.

       The main way to create an asynchronous file object is by using the
       :func:`trio.open_file` function.
