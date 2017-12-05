Contributing to Trio and related projects
=========================================

So you're interested in contributing to Trio or `one of our associated
projects <https://github.com/python-trio>`__? That's awesome! Trio is
is an open-source project maintained by an informal group of
volunteers. Our goal is to make async I/O in Python more fun, easy,
and reliable, and we can't do it without help from people like you. We
welcome contributions from anyone willing to work in good faith with
other contributors and the community (see also our
:ref:`code-of-conduct`).

There are many ways to contribute, no contribution is too small, and
all contributions are valued.  For example, you could:

- Hang out in our `chatroom <https://gitter.im/python-trio/general>`__
  and help people with questions.
- Answer questions on StackOverflow (`recent questions
  <https://stackexchange.com/filters/289914/trio-project-tags-on-stackoverflow-filter>`__).
- Use Trio in a project, and give us feedback on what worked and what
  didn't.
- Write a blog post about your experiences with Trio, good or bad.
- Release open-source programs and libraries that use Trio.
- Improve documentation.
- Comment on issues.
- Add tests.
- Fix bugs.
- Add features.

We want contributing to be enjoyable and mutually beneficial; this
document tries to give you some tips to help that happen, and applies
to all of the projects under the `python-trio organization on Github
<https://github.com/python-trio>`__. If you have thoughts on how it
can be improved then please let us know.


Getting started
---------------

If you're new to open source in general, you might find it useful to
check out `opensource.guide's How to Contribute to Open Source
tutorial <https://opensource.guide/how-to-contribute/>`__, or if
video's more your thing, `egghead.io has a short free video course
<https://egghead.io/courses/how-to-contribute-to-an-open-source-project-on-github>`__.

Trio and associated projects are developed on GitHub, under the
`python-trio <https://github.com/python-trio>`__ organization. Code
and documentation changes are made through pull requests (see
:ref:`preparing-pull-requests` below).

We also have an unusual policy for managing commit rights: anyone
whose pull request is merged is automatically invited to join the
GitHub organization, and gets commit rights to all of our
repositories. See :ref:`joining-the-team` below for more details.


Providing support
-----------------

When helping others use Trio, please remember that you are
representing our community, and we want this to be a friendly and
welcoming place.

Concurrency is *really confusing* when you're first learning. When
talking to beginners, remember that you were a beginner once too, and
the whole goal here is to make a top-tier concurrency library that's
accessible to everyone and a joy to use. If people are showing up with
beginner questions, *that means we're succeeding*. How we respond to
questions is part of that developer experience, just as much as our
API, documentation, or testing tools. And as a bonus, helping
beginners is often the best way to discover ideas for improvements. If
you start getting burned out and cranky, we've all been there, and
it's OK to take a break until you feel better. But it's not OK to take
that out on random users.

Please remember that the authors and users of competing projects are
smart, thoughtful people doing their best to balance complicated and
conflicting requirements, just like us. Of course it's totally fine to
make specific technical critiques ("In project X, this is handled by
doing Y, Trio does Z instead, which I prefer because...") or talk
about your personal experience ("I tried using X but I got super
frustrated and confused"), but refrain from generic statements like "X
sucks" or "I can't believe anyone uses X".

Please try not to make assumptions about people's gender, and in
particular remember that we're not all dudes. If you don't have a
any specific reason to assume otherwise, then `singular they
<https://en.wikipedia.org/wiki/Third-person_pronoun#Singular_they>`__
makes a fine pronoun, and there are plenty of gender-neutral
collective terms: "Hey folks", "Hi all", ...

We also like the Recurse Center's `social rules
<https://www.recurse.com/manual#sub-sec-social-rules>`__:

* no feigning surprise (also available in a `sweet comic version
  <https://jvns.ca/blog/2017/04/27/no-feigning-surprise/>`__)
* no well-actually's
* no subtle -isms (`more details <https://www.recurse.com/blog/38-subtle-isms-at-hacker-school>`__)


.. _preparing-pull-requests:

Preparing pull requests
-----------------------

If you want to submit a documentation or code change to one of the
Trio projects, then that's done by preparing a Github pull request (or
"PR" for short). We'll do our best to review your PR quickly. If it's
been a week or two and you're still waiting for a response, feel free
to post a comment poking us. (This can just be a comment with the
single word "ping"; it's not rude at all.)

Here's a quick checklist for putting together a good PR, with details
in separate sections below:

* :ref:`pull-request-scope`: Does your PR address a single,
  self-contained issue?

* :ref:`pull-request-tests`: Are your tests passing? Did you add any
  necessary tests? Code changes pretty much always require test
  changes, because if it's worth fixing the code then it's worth
  adding a test to make sure it stays fixed.

* :ref:`pull-request-formatting`: If you changed Python code, then did
  you run ``yapf -rpi setup.py trio``? (Or for other packages, replace
  ``trio`` with the package name.)

* :ref:`pull-request-release-notes`: If your change affects
  user-visible functionality, then did you add a release note to the
  ``newsfragments/`` directory?

* :ref:`pull-request-docs`: Did you make any necessary documentation
  updates?

* License: by submitting a PR to a Trio project, you're offering your
  changes under that project's license. For most projects, that's dual
  MIT/Apache 2, except for cookiecutter-trio, which is CC0.


.. _pull-request-scope:

What to put in a PR
~~~~~~~~~~~~~~~~~~~

Each PR should, as much as possible, address just one issue and be
self-contained. If you have ten small, unrelated changes, then go
ahead and submit ten PRs – it's much easier to review ten small
changes than one big change with them all mixed together, and this way
if there's some problem with one of the changes it won't hold up all
the others.

If you're uncertain about whether a change is a good idea and want
some feedback before putting time into it, feel free to ask in an
issue or in the chat room. If you have a partial change that you want
to get feedback on, feel free to submit it as a PR. (In this case it's
traditional to start the PR title with ``[WIP]``, for "work in
progress".)


.. _pull-request-tests:

Tests
~~~~~

We use `pytest <https://pytest.org/>`__ for testing. To run the tests
locally, you should run:

* ``cd path/to/project/checkout/``
* ``pip install -r test-requirements.txt`` (possibly using a
  virtualenv)
* ``pytest <projectname>``

This doesn't try to be completely exhaustive – it only checks that
things work on your machine, and it may skip some slow tests. But it's
a good way to quickly check that things seem to be working, and we'll
automatically run the full test suite when your PR is submitted, so
you'll have a chance to see and fix any remaining issues then.

Every change should have 100% coverage for both code and tests. But,
you can use ``# pragma: no cover`` to mark lines where
lack-of-coverage isn't something that we'd want to fix (as opposed to
it being merely hard to fix). For example::

    else:  # pragma: no cover
        raise AssertionError("this can't happen!")

We use Codecov to track coverage, because it makes it easy to combine
coverage from running in different configurations. Running coverage
locally can be useful
(``pytest --cov=PACKAGENAME --cov-report=html``), but don't be
surprised if you get lower coverage than when looking at Codecov
reports, because there are some lines that are only executed on
Windows, or MacOS, or PyPy, or CPython, or... you get the idea. After
you create a PR, Codecov will automatically report back with the
coverage, so you can check how you're really doing. (But note that the
results can be inaccurate until all the tests are passing. If the
tests failed, then fix that before worrying about coverage.)

Some rules for writing good tests:

* `Tests MUST pass deterministically
  <https://github.com/python-trio/trio/issues/200>`__. Flakey tests
  make for miserable developers. One common source of indeterminism is
  scheduler ordering; if you're having trouble with this, then
  :mod:`trio.testing` provides powerful tools to help control
  ordering, like :func:`trio.testing.wait_all_tasks_blocked`,
  :class:`trio.testing.Sequencer`, and :class:`trio.testing.MockClock`
  (usually used as a fixture: ``async def
  test_whatever(autojump_clock): ...``). And if you need more tools
  than this then we should add them.

* (Trio package only) Slow tests – anything that takes more than about
  0.25 seconds – should be marked with ``@slow``. This makes it so they
  only run if you do ``pytest trio --run-slow``. Our CI scripts do
  run slow tests, so you can be sure that the code will still be
  thoroughly tested, and this way you don't have to sit around waiting
  for a few irrelevant multi-second tests to run while you're iterating
  on a change locally.

  You can check for slow tests by passing ``--durations=10`` to
  pytest. Most tests should take 0.01 seconds or less.

* Speaking of waiting around for tests: Tests should never sleep
  unless *absolutely* necessary. However, calling :func:`trio.sleep`
  when using ``autojump_clock`` is fine, because that's not really
  sleeping, and doesn't waste developers time waiting for the test to
  run.

* We like tests to exercise real functionality. For example, if you're
  adding subprocess spawning functionality, then your tests should
  spawn at least one process! Sometimes this is tricky – for example,
  Trio's :class:`KeyboardInterrupt` tests have to jump through quite
  some hoops to generate real SIGINT signals at the right times to
  exercise different paths. But it's almost always worth it.

* For cases where real testing isn't relevant or sufficient, then we
  strongly prefer fakes or stubs over mocks. Useful articles:

* `Test Doubles - Fakes, Mocks and Stubs
  <https://dev.to/milipski/test-doubles---fakes-mocks-and-stubs>`__

  * `Mocks aren't stubs
    <https://martinfowler.com/articles/mocksArentStubs.html>`__

  * `Write test doubles you can trust using verified fakes
    <https://codewithoutrules.com/2016/07/31/verified-fakes/>`__

  Most major features have both real tests and tests using fakes or
  stubs. For example, :class:`~trio.ssl.SSLStream` has some tests that
  use Trio to make a real socket connection to real SSL server
  implemented using blocking I/O, because it sure would be
  embarrassing if that didn't work. And then there are also a bunch of
  tests that use a fake in-memory transport stream where we have
  complete control over timing and can make sure all the subtle edge
  cases work correctly.

Writing reliable tests for obscure corner cases is often harder than
implementing a feature in the first place, but stick with it: it's
worth it! And don't be afraid to ask for help. Sometimes a fresh pair
of eyes can be helpful when trying to come up with devious tricks.


.. _pull-request-formatting:

Code formatting
~~~~~~~~~~~~~~~

Instead of wasting time arguing about code formatting, we use `yapf
<https://github.com/google/yapf>`__ to automatically format all our
code to a standard style. While you're editing code you can be as
sloppy as you like about whitespace; and then before you commit, just
run::

    pip install -U yapf
    yapf -rpi setup.py trio

to fix it up. (And don't worry if you forget – when you submit a pull
request then we'll automatically check and remind you.) Hopefully this
will let you focus on more important style issues like choosing good
names, writing useful comments, and making sure your docstrings are
nicely formatted. (Yapf doesn't reformat comments or docstrings.)

Very occasionally, yapf will generate really ugly and unreadable
formatting (usually for large literal structures like dicts nested
inside dicts). In these cases, you can add a ``# yapf: disable``
comment to tell it to leave that particular statement alone.

If you want to see what changes yapf will make, you can use::

  yapf -rpd setup.py trio

(``-d`` displays a diff, versus ``-i`` which fixes files in-place.)


.. _pull-request-release-notes:

Release notes
~~~~~~~~~~~~~

We use `towncrier <https://github.com/hawkowl/towncrier>`__ to manage
our release notes. Basically, every pull request that has a user
visible effect should add a short file to the ``newsfragments/``
directory describing the change, with a name like ``<ISSUE
NUMBER>.<TYPE>.rst``. See `newsfragments/README.rst
<https://github.com/python-trio/trio/blob/master/newsfragments/README.rst>`__
for details. This way we can keep a good list of changes as we go,
which makes the release manager happy, which means we get more
frequent releases, which means your change gets into users' hands
faster.


.. _pull-request-commit-messages:

Commit messages
~~~~~~~~~~~~~~~

We don't enforce any particular format on commit messages. In your
commit messages, try to give the context to explain *why* a change was
made.

The target audience for release notes is users, who want to find out
about changes that might affect how they use the library, or who are
trying to figure out why something changed after they upgraded.

The target audience for commit messages is some hapless developer
(think: you in six months... or five years) who is trying to figure
out why some code looks the way it does. Including links to issues and
any other discussion that led up to the commit is *strongly*
recommended.


.. _pull-request-docs:

Documentation
~~~~~~~~~~~~~

We take pride in providing friendly and comprehensive documentation.
Documentation is stored in ``docs/source/*.rst`` and is rendered using
`Sphinx <http://www.sphinx-doc.org/>`__ with the `sphinxcontrib-trio
<https://sphinxcontrib-trio.readthedocs.io/en/latest/>`__ extension.
Documentation is hosted at `Read the Docs
<https://readthedocs.org/>`__, who take care of automatically
rebuilding it after every commit.

For docstrings, we use `the Google docstring format
<http://www.sphinx-doc.org/en/stable/ext/example_google.html#example-google>`__.
If you add a new function or class, there's no mechanism for
automatically adding that to the docs: you'll have to at least add a
line like ``.. autofunction:: <your function>`` in the appropriate
place. In many cases it's also nice to add some longer-form narrative
documentation around that.

We enable Sphinx's "nitpick mode", which turns dangling references
into an error – this helps catch typos. (This will be automatically
checked when your PR is submitted.) If you intentionally want to allow
a dangling reference, you can add it to the ``nitpick_ignore``
whitelist in ``docs/source/conf.py``.


.. _joining-the-team:

Joining the team
----------------

After your first PR is merged, you should receive a Github invitation
to join the ``python-trio`` organization. If you don't, that's not
your fault, it's because we made a mistake on our end. Give us a
nudge on chat or `send @njsmith an email <mailto:njs@pobox.com>`__ and
we'll fix it.

It's totally up to you whether you accept or not, and if you do
accept, you're welcome to participate as much or as little as you
want. We're offering the invitation because we'd love for you to join
us in making Python concurrency more friendly and robust, but there's
no pressure: life is to short to spend volunteer time on things that
don't find fulfilling.

At this point people tend to have questions.

**How can you trust me with this kind of power? What if I mess
everything up?!?**

Relax, you got this! And we've got your back. Remember, it's just
software, and everything's in version control: worst case we'll just
roll things back and brainstorm ways to avoid the issue happening
again. We think it's more important to welcome people and help them
grow than to worry about the occasional minor mishap.

**I don't think I really deserve this.**

It's up to you, but we wouldn't be offering if we didn't think
you did.

**What exactly happens if I accept? Does it mean I'll break everything
if I click the wrong button?**

Concretely, if you accept the invitation, this does three things:

* It lets you manage incoming issues on all of the ``python-trio``
  projects by labelling them, closing them, etc.

* It lets you merge pull requests on all of the ``python-trio``
  projects by clicking Github's big green "Merge" button, but only if
  all their tests have passed.

* It automatically subscribes you to notifications on the
  ``python-trio`` repositories (but you can unsubscribe again if you
  want through the Github interface)

Note that it does *not* allow you to push changes directly to Github
without submitting a PR, and it doesn't let you merge broken PRs –
this is enforced through Github's "branch protection" feature, and it
applies to everyone from the newest contributor up to the project
founder.

**Okay, that's what I CAN do, but what SHOULD I do?**

Short answer: whatever you feel comfortable with.

We do have one rule, which is the same one most F/OSS projects use:
don't merge your own PRs. We find that having another person look at
each PR leads to better quality. (Exception: you may see `@njsmith
<https://github.com/njsmith>`__ merging his own PRs. This happens
because he is lonely and has no-one to review them for him. It would
make him happy if you reviewed and – if they look good – merged his
PRs.)

Beyond that, it all comes down to what you feel up to. If you don't
feel like you know enough to review a complex code change, then you
don't have to – you can just look it over and make some comments, even
if you don't feel up to making the final merge/no-merge decison. Or
you can just stick to merging trivial doc fixes and adding tags to
issues, that's helpful too. If after hanging around for a while you
start to feel like you have better handle on how things work and want
to start doing more, that's excellent; if it doesn't happen, that's
fine too.

If at any point you're unsure about whether doing something would be
appropriate, feel free to ask (for example, in our chat room or by
posting Github comment). For example, it's *totally OK* if the first
time you review a PR, you want someone else to check over your work
before you hit the merge button.

For general tips on doing code reviews, the `node.js guide
<https://github.com/nodejs/node/blob/master/CONTRIBUTING.md#reviewing-pull-requests>`__
has some good suggestions, and `so does this blog post
<http://verraes.net/2013/10/pre-merge-code-reviews/>`__.


Governance
----------

`Nathaniel J. Smith <https://github.com/njsmith>`__ is the Trio `BDFL
<https://en.wikipedia.org/wiki/Benevolent_dictator_for_life>`__. If
the project grows to the point where we'd benefit from more structure,
then we'll figure something out.


.. Possible references for future additions:

   """
   Jumping into an unfamiliar codebase (or any for that matter) for the first time can be scary. Plus, if it’s your first time contributing to open source, it can even be scarier!

   But, we at webpack believe:

       Any (even non-technical) individual should feel welcome to contribute.
       However you decide to contribute, it should be fun and enjoyable for you!
       Even after your first commit, you will walk away understanding more about webpack or JavaScript.
       Consequently, you could become a better developer, writer,
         designer, etc. along the way, and we are committed to helping
         foster this growth.
   """

   imposter syndrome disclaimer
   https://github.com/Unidata/MetPy#contributing

   checklist
   https://github.com/nayafia/contributing-template/blob/master/CONTRIBUTING-template.md

   https://medium.com/the-node-js-collection/healthy-open-source-967fa8be7951

   http://sweng.the-davies.net/Home/rustys-api-design-manifesto
