This directory collects "newsfragments": short files that each contain
a snippet of ReST-formatted text that will be added to the next
release notes. This should be a description of aspects of the change
(if any) that are relevant to users. (This contrasts with your commit
message and PR description, which are a description of the change as
relevant to people working on the code itself.)

Each file should be named like ``<ISSUE>.<TYPE>.rst``, where
``<ISSUE>`` is an issue numbers, and ``<TYPE>`` is one of:

* ``feature``
* ``bugfix``
* ``doc``
* ``removal``
* ``misc``

So for example: ``123.feature.rst``, ``456.bugfix.rst``

If your PR fixes an issue, use that number here. If there is no issue,
then after you submit the PR and get the PR number you can add a
newsfragment using that instead.

Note that the ``towncrier`` tool will automatically
reflow your text, so don't try to do any fancy formatting. You can
install ``towncrier`` and then run ``towncrier --draft`` if you want
to get a preview of how your change will look in the final release
notes.
