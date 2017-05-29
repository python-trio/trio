:orphan:

.. _glossary:

********
Glossary
********

.. glossary::

   asynchronous file object
       This is an object with an API identical to a :term:`file object`,
       with the exception that all nontrivial methods are wrapped in coroutine
       functions.

       Like file objects, there are also three categories of asynchronous file
       objects, corresponding to each file object type. Their interfaces are
       defined in the :mod:`trio.io.types` module. The main way to create an
       asynchronous file object is by using the :func:`trio.io.open` function.
