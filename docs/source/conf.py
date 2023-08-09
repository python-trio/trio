#!/usr/bin/env python3
#
# Trio documentation build configuration file, created by
# sphinx-quickstart on Sat Jan 21 19:11:14 2017.
#
# This file is execfile()d with the current directory set to its
# containing dir.
#
# Note that not all possible configuration values are present in this
# autogenerated file.
#
# All configuration values have a default; values that are commented out
# serve to show the default.

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
import re

# For our local_customization module
sys.path.insert(0, os.path.abspath("."))
# For trio itself
sys.path.insert(0, os.path.abspath("../.."))

# https://docs.readthedocs.io/en/stable/builds.html#build-environment
if "READTHEDOCS" in os.environ:
    import glob

    if glob.glob("../../newsfragments/*.*.rst"):
        print("-- Found newsfragments; running towncrier --", flush=True)
        import subprocess

        subprocess.run(
            ["towncrier", "--yes", "--date", "not released yet"],
            cwd="../..",
            check=True,
        )

# Warn about all references to unknown targets
nitpicky = True
# Except for these ones, which we expect to point to unknown targets:
nitpick_ignore = [
    ("py:class", "CapacityLimiter-like object"),
    ("py:class", "bytes-like"),
    ("py:class", "None"),
    # Was removed but still shows up in changelog
    ("py:class", "trio.lowlevel.RunLocal"),
    # trio.abc is documented at random places scattered throughout the docs
    ("py:mod", "trio.abc"),
    ("py:class", "math.inf"),
    ("py:exc", "Anything else"),
    ("py:class", "async function"),
    ("py:class", "sync function"),
    # https://github.com/sphinx-doc/sphinx/issues/7722
    # TODO: why do these need to be spelled out?
    ("py:class", "trio._abc.ReceiveType"),
    ("py:class", "trio._abc.SendType"),
    ("py:class", "trio._abc.T"),
    ("py:obj", "trio._abc.ReceiveType"),
    ("py:obj", "trio._abc.SendType"),
    ("py:obj", "trio._abc.T"),
    ("py:obj", "trio._abc.T_resource"),
    ("py:class", "trio._threads.T"),
    # why aren't these found in stdlib?
    ("py:class", "types.FrameType"),
    ("py:class", "P.args"),
    ("py:class", "P.kwargs"),
    ("py:class", "RetT"),
    # TODO: figure out if you can link this to SSL
    ("py:class", "Context"),
    # TODO: temporary type
    ("py:class", "_SocketType"),
    # these are not defined in https://docs.python.org/3/objects.inv
    ("py:class", "socket.AddressFamily"),
    ("py:class", "socket.SocketKind"),
]
autodoc_inherit_docstrings = False
default_role = "obj"

# These have incorrect __module__ set in stdlib and give the error
# `py:class reference target not found`
# Some of the nitpick_ignore's above can probably be fixed with this.
# See https://github.com/sphinx-doc/sphinx/issues/8315#issuecomment-751335798
autodoc_type_aliases = {
    # aliasing doesn't actually fix the warning for types.FrameType, but displaying
    # "types.FrameType" is more helpful than just "frame"
    "FrameType": "types.FrameType",
}


def autodoc_process_signature(
    app, what, name, obj, options, signature, return_annotation
):
    """Modify found signatures to fix various issues."""
    if signature is not None:
        if name.startswith("trio.testing"):
            # Expand type aliases
            signature = re.sub(
                r"StreamMaker\[([a-zA-Z ,]+)]",
                lambda match: f"typing.Callable[[], typing.Awaitable[tuple[{match.group(1)}]]]",
                signature,
            )
            signature = signature.replace(
                "AsyncHook", "typing.Callable[[], typing.Awaitable[object]]"
            )
            signature = signature.replace("SyncHook", "typing.Callable[[], object]")

    return signature, return_annotation


# XX hack the RTD theme until
#   https://github.com/rtfd/sphinx_rtd_theme/pull/382
# is shipped (should be in the release after 0.2.4)
# ...note that this has since grown to contain a bunch of other CSS hacks too
# though.
def setup(app):
    app.add_css_file("hackrtd.css")
    app.connect("autodoc-process-signature", autodoc_process_signature)


# -- General configuration ------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.coverage",
    "sphinx.ext.napoleon",
    "sphinxcontrib_trio",
    "sphinxcontrib.jquery",
    "local_customization",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "outcome": ("https://outcome.readthedocs.io/en/latest/", None),
    "pyopenssl": ("https://www.pyopenssl.org/en/stable/", None),
    "sniffio": ("https://sniffio.readthedocs.io/en/latest/", None),
}

autodoc_member_order = "bysource"

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = ".rst"

# The master toctree document.
master_doc = "index"

# General information about the project.
project = "Trio"
copyright = "2017, Nathaniel J. Smith"
author = "Nathaniel J. Smith"

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The short X.Y version.
import trio

version = trio.__version__
# The full version, including alpha/beta/rc tags.
release = version

html_favicon = "_static/favicon-32.png"
html_logo = "../../logo/wordmark-transparent.svg"
# & down below in html_theme_options we set logo_only=True

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = "en"

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This patterns also effect to html_static_path and html_extra_path
exclude_patterns = []

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "default"

highlight_language = "python3"

# If true, `todo` and `todoList` produce output, else they produce nothing.
todo_include_todos = False

# This avoids a warning by the epub builder that it can't figure out
# the MIME type for our favicon.
suppress_warnings = ["epub.unknown_project_files"]


# -- Options for HTML output ----------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
# html_theme = 'alabaster'

# We have to set this ourselves, not only because it's useful for local
# testing, but also because if we don't then RTD will throw away our
# html_theme_options.
import sphinx_rtd_theme

html_theme = "sphinx_rtd_theme"
html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
html_theme_options = {
    # default is 2
    # show deeper nesting in the RTD theme's sidebar TOC
    # https://stackoverflow.com/questions/27669376/
    # I'm not 100% sure this actually does anything with our current
    # versions/settings...
    "navigation_depth": 4,
    "logo_only": True,
    "prev_next_buttons_location": "both",
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]


# -- Options for HTMLHelp output ------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = "Triodoc"


# -- Options for LaTeX output ---------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',
    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',
    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',
    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, "Trio.tex", "Trio Documentation", "Nathaniel J. Smith", "manual"),
]


# -- Options for manual page output ---------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [(master_doc, "trio", "Trio Documentation", [author], 1)]


# -- Options for Texinfo output -------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (
        master_doc,
        "Trio",
        "Trio Documentation",
        author,
        "Trio",
        "One line description of project.",
        "Miscellaneous",
    ),
]
