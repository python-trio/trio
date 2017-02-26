I/O in Trio
===========

Sockets and networking
----------------------

.. module:: trio.socket

.. autofunction:: getaddrinfo

.. autoclass:: trio.socket.SocketType()

   .. method:: connect

   .. method:: send

   .. method:: recv


The abstract Stream API
-----------------------

.. currentmodule:: trio

.. autoclass:: AsyncResource
   :members:
   :undoc-members:

.. autoclass:: SendStream
   :members:
   :undoc-members:

.. autoclass:: RecvStream
   :members:
   :undoc-members:

.. autoclass:: Stream
   :members:
   :undoc-members:


TLS support
-----------

`Not implemented yet! <https://github.com/njsmith/trio/issues/9>`__


Subprocesses
------------

`Not implemented yet! <https://github.com/njsmith/trio/issues/4>`__


Signals
-------

.. currentmodule:: trio

.. autofunction:: catch_signals
   :with:
