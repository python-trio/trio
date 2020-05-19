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

      - ``git rm`` changes

   + commit

* push to your personal repository

* create pull request to ``python-trio/trio``'s "master" branch

* verify that all checks succeeded

* tag with vVERSION, push tag

* push to PyPI::

    git clean -xdf   # maybe run 'git clean -xdn' first to see what it will delete
    python3 setup.py sdist bdist_wheel
    twine upload dist/*

* update version number in the same pull request

   + add ``+dev`` tag to the end

* merge the release pull request

* announce on gitter
