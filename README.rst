.. image:: https://readthedocs.org/projects/trio/badge/?version=latest
   :target: http://trio.readthedocs.io/en/latest/?badge=latest
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

Trio is an attempt to produce a production-quality, `permissively
licensed <https://github.com/python-trio/trio/blob/master/LICENSE>`__,
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
chance to give feedback about any potential compatibility-breaking
changes.


Where to next?
--------------

**I want to try it out!** Awesome! We have a `friendly tutorial
<https://trio.readthedocs.io/en/latest/tutorial.html>`__ to get you
started; no prior experience with async coding is required.

**Ugh, I don't want to read all that – show me some code!** It's a
good tutorial, Brent! But if you're impatiant, here's a `simple
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

**I want to help!** You're the best! There's tons of work to do –
filling in missing functionality, building up an ecosystem of
trio-using libraries, usability testing (e.g., maybe try teaching
yourself or a friend to use trio and make a list of every error
message you hit and place where you got confused?), improving the
docs, ... We `don't have a CONTRIBUTING.md yet
<https://github.com/python-trio/trio/issues/46>`__ (want to help write
one?), but you can check out our `issue tracker
<https://github.com/python-trio/trio/issues>`__, and depending on your
interests check out our `labels
<https://github.com/python-trio/trio/labels>`__ for `low-hanging fruit
<https://github.com/python-trio/trio/labels/todo%20soon>`__, `significant
missing functionality
<https://github.com/python-trio/trio/labels/missing%20piece>`__, `open
questions regarding high-level design
<https://github.com/python-trio/trio/labels/design%20discussion>`__, ...

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

     and assert_yields stuff might make more sense in core

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

   - wait_send_buffer_available()

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

   - start_* convention -- if you want to run it synchronously, do
     async with make_nursery() as nursery:
         task = await start_foo(nursery)
     return task.result.unwrap()
     we might even want to wrap this idiom up in a convenience function

     for our server helper, it's a start_ function
     maybe it takes listener_nursery, connection_nursery arguments, to let you
     set up the graceful shutdown thing? though draining is still a
     problem. I guess just a matter of setting a deadline?

   - should we provide a start_nursery?

     problem: an empty nursery would close itself before start_nursery
     even returns!

     maybe as minimal extension to the existing thing,
     open_nursery(autoclose=False), only closes when cancelled?

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
<https://github.com/python-trio/trio/blob/master/CODE_OF_CONDUCT.md>`__ in
all project spaces.
