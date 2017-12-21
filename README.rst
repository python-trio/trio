.. image:: https://img.shields.io/badge/chat-join%20now-blue.svg
   :target: https://gitter.im/python-trio/general
   :alt: Join chatroom

.. image:: https://img.shields.io/badge/docs-read%20now-blue.svg
   :target: https://trio.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation Status

.. image:: https://travis-ci.org/python-trio/trio.svg?branch=master
   :target: https://travis-ci.org/python-trio/trio
   :alt: Automated test status (Linux and MacOS)

.. image:: https://ci.appveyor.com/api/projects/status/af4eyed8o8tc3t0r/branch/master?svg=true
   :target: https://ci.appveyor.com/project/python-trio/trio/history
   :alt: Automated test status (Windows)

.. image:: https://codecov.io/gh/python-trio/trio/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/python-trio/trio
   :alt: Test coverage

Trio – async I/O for humans and snake people
============================================

*P.S. your API is a user interface – Kenneth Reitz*

.. Github carefully breaks rendering of SVG directly out of the repo,
   so we have to redirect through cdn.rawgit.com
   See:
     https://github.com/isaacs/github/issues/316
     https://github.com/github/markup/issues/556#issuecomment-288581799
   I also tried rendering to PNG and linking to that locally, which
   "works" in that it displays the image, but for some reason it
   ignores the width and align directives, so it's actually pretty
   useless...

.. image:: https://cdn.rawgit.com/python-trio/trio/9b0bec646a31e0d0f67b8b6ecc6939726faf3e17/logo/logo-with-background.svg
   :width: 200px
   :align: right

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


Where to next?
--------------

**I want to try it out!** Awesome! We have a `friendly tutorial
<https://trio.readthedocs.io/en/latest/tutorial.html>`__ to get you
started; no prior experience with async coding is required.

**Ugh, I don't want to read all that – show me some code!** It's a
good tutorial, Brent! But if you're impatient, here's a `simple
concurrency example
<https://trio.readthedocs.io/en/latest/tutorial.html#tutorial-example-tasks-intro>`__,
an `echo client
<https://trio.readthedocs.io/en/latest/tutorial.html#tutorial-echo-client-example>`__,
and an `echo server
<https://trio.readthedocs.io/en/latest/tutorial.html#tutorial-echo-server-example>`__.

**Cool, but will it work on my system?** Probably! As long as you have
some kind of Python 3.5-or-better (CPython or the latest PyPy3 are
both fine), and are using Linux, MacOS, or Windows, then trio should
absolutely work. *BSD and illumos likely work too, but we don't have
testing infrastructure for them. All of our dependencies are pure
Python, except for CFFI on Windows, and that has wheels available, so
installation should be easy.

**I tried it but it's not working.** Sorry to hear that! You can try
asking for help in our `chat room
<https://gitter.im/python-trio/general>`__, `filing a bug
<https://github.com/python-trio/trio/issues/new>`__, or `posting a
question on StackOverflow
<https://stackoverflow.com/questions/ask?tags=python+trio>`__, and
we'll do our best to help you out.

**Trio is awesome and I want to help make it more awesome!** You're
the best! There's tons of work to do – filling in missing
functionality, building up an ecosystem of trio-using libraries,
usability testing (e.g., maybe try teaching yourself or a friend to
use trio and make a list of every error message you hit and place
where you got confused?), improving the docs, ... check out our `guide
for contributors
<https://trio.readthedocs.io/en/latest/contributing.html>`!

**I don't have any immediate plans to use it, but I love geeking out
about I/O library design!** That's a little weird? But tbh you'll fit
in great around here. Check out our `discussion of design choices
<https://trio.readthedocs.io/en/latest/design.html#user-level-api-principles>`__,
`reading list
<https://github.com/python-trio/trio/wiki/Reading-list>`__, and
`issues tagged design-discussion
<https://github.com/python-trio/trio/labels/design%20discussion>`__.

**I want to make sure my company's lawyers won't get angry at me!** No
worries, trio is permissively licensed under your choice of MIT or
Apache 2. See `LICENSE
<https://github.com/python-trio/trio/blob/master/LICENSE>`__ for details.


..
   next:
   - @_testing for stuff that needs tighter integration? kinda weird
     that wait_all_tasks_blocked is in hazmat right now

     and assert_checkpoints stuff might make more sense in core

   - make @trio_test accept clock_rate=, clock_autojump_threshold=
     arguments
     and if given then it automatically creates a clock with those
     settings and uses it; can be accessed via current_clock()
     while also doing the logic to sniff for a clock fixture
     (and of course error if used kwargs *and* a fixture)

   - a thought: if we switch to a global parkinglot keyed off of
     arbitrary hashables, and put the key into the task object, then
     introspection will be able to do things like show which tasks are
     blocked on the same mutex. (moving the key into the task object
     in general lets us detect which tasks are parked in the same lot;
     making the key be an actual synchronization object gives just a
     bit more information. at least in some cases; e.g. currently
     queues use semaphores internally so that's what you'd see in
     introspection, not the queue object.)

     alternatively, if we have an system for introspecting where tasks
     are blocked through stack inspection, then maybe we can re-use
     that? like if there's a magic local pointing to the frame, we can
     use that frame's 'self'?

   - add nursery statistics? add a task statistics method that also
     gives nursery statistics? "unreaped tasks" is probably a useful
     metric... maybe we should just count that at the runner
     level. right now the runner knows the set of all tasks, but not
     zombies.

     (task statistics are closely related)

   - make sure to @ki_protection_enabled all our __(a)exit__
     implementations. Including @acontextmanager! it's not enough to
     protect the wrapped function. (Or is it? Or maybe we need to do
     both? I'm not sure what the call-stack looks like for a
     re-entered generator... and ki_protection for async generators is
     a bit of a mess, ugh. maybe ki_protection needs to use inspect to
     check for generator/asyncgenerator and in that case do the local
     injection thing. or maybe yield from.)

     I think there is an unclosable loop-hole here though b/c we can't
     enable @ki_protection atomically with the entry to
     __(a)exit__. If a KI arrives just before entering __(a)exit__,
     that's OK. And if it arrives after we've entered and the
     callstack is properly marked, that's also OK. But... since the
     mark is on the frame, not the code, we can't apply the mark
     instantly when entering, we need to wait for a few bytecode to be
     executed first. This is where having a bytecode flag or similar
     would be useful. (Or making it possible to attach attributes to
     code objects. I guess I could violently subclass CodeType, then
     swap in my new version... ugh.)

     I'm actually not 100% certain that this is even possible at the
     bytecode level, since exiting a with block seems to expand into 3
     separate bytecodes?

   - possible improved robustness ("quality of implementation") ideas:
     - if an abort callback fails, discard that task but clean up the
       others (instead of discarding all)
     - if a clock raises an error... not much we can do about that.

   - trio
     http://infolab.stanford.edu/trio/ -- dead for a ~decade
     http://inamidst.com/sw/trio/ -- dead for a ~decade


Code of conduct
---------------

Contributors are requested to follow our `code of conduct
<https://trio.readthedocs.io/en/latest/code-of-conduct.html>`__ in all
project spaces.
