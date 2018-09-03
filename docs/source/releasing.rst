.. _releasing:

Preparing a release
-------------------

Things to do for releasing:

* announce intent to release on gitter

* check for open issues / pull requests that really should be in the release

   + come back when these are done

   + … or ignore them and do another release next week

* check for deprecations "long enough ago" (two months or two releases, whichever is longer)

   + remove affected code

* Do the actual release changeset

   + update version number

      - increment as per Semantic Versioning rules

      - remove ``+dev`` tag from version number

   + Run ``towncrier``

      - review history change

      - ``git rm`` changes

   + commit

* push to your personal repository

* create pull request to ``python-trio/trio``'s "master" branch

* announce PR on gitter

   + wait for feedback

   + fix problems, if any

* verify that all checks succeeded

* acknowledge the release PR

   + or rather, somebody else should do that

* tag with vVERSION

* push to PyPI

   + ``python3 setup.py sdist bdist_wheel upload``

* announce on gitter

* update version number

   + add ``+dev`` tag to the end

* prepare another pull request to "master"

   + acknowledge it

