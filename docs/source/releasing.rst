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

   + bump version number

      - increment as per Semantic Versioning rules

      - remove ``+dev`` tag from version number

   + Run ``towncrier``

      - review history change

      - ``git rm`` the now outdated newfragments

   + commit

* push to your personal repository

* create pull request to ``python-trio/trio``'s "main" branch

* verify that all checks succeeded

* tag with vVERSION, push tag on ``python-trio/trio`` (not on your personal repository)

* push to PyPI:

  .. code-block::

    git clean -xdf   # maybe run 'git clean -xdn' first to see what it will delete
    python3 -m build
    twine upload dist/*

* update version number in the same pull request

   + add ``+dev`` tag to the end

* merge the release pull request

* make a GitHub release (go to the tag and press "Create release from tag")

   + paste in the new content in ``history.rst`` and convert it to markdown: turn the parts under section into ``---``, update links to just be the links, and whatever else is necessary.

   + include anything else that might be pertinent, like a link to the commits between the latest and current release.

* announce on gitter
