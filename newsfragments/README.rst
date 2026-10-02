This directory collects "newsfragments": short files that each contain
a snippet of ReST-formatted text that will be added to the next
release notes. This should be a description of aspects of the change
(if any) that are relevant to users. (This contrasts with your commit
message and PR description, which are a description of the change as
relevant to people working on the code itself.)

Each file should be named like ``<ISSUE>.<TYPE>.rst``, where
``<ISSUE>`` is an issue number, and ``<TYPE>`` is one of:

* ``headline``: a major new feature we want to highlight for users
* ``breaking``: any breaking changes that happen without a proper
  deprecation period (note: deprecations, and removal of previously
  deprecated features after an appropriate time, go in the
  ``deprecated`` category instead)
* ``feature``: any new feature that doesn't qualify for ``headline``
* ``removal``: removing support for old python versions, or other removals with no deprecation period.
* ``bugfix``
* ``doc``
* ``deprecated``
* ``misc``

So for example: ``123.headline.rst``, ``456.bugfix.rst``,
``789.deprecated.rst``

If your PR fixes an issue, use that number here. If there is no issue,
then after you submit the PR and get the PR number you can add a
newsfragment using that instead.

Your text can use all the same markup that we use in our Sphinx docs.
For example, you can use double-backticks to mark code snippets, or
single-backticks to link to a function/class/module.

To check syntax and references locally, install the documentation dependencies
in your development environment and run the existing Sphinx dummy builder:

.. code-block:: shell

   python -m pip install -r docs-requirements.txt
   make -C docs dummy SPHINXOPTS="-E -W --keep-going"

This checks the assembled changelog and documentation without generating HTML.
Warnings cause the command to fail; ``-E`` ensures edited fragments are reread.

To check how your formatting looks, the easiest way is to make the PR,
and then after the CI checks run, click on the "Read the Docs build"
details link, and navigate to the release history page.
