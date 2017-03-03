# Inspirations:
#   https://github.com/python/cpython/blob/master/Doc/tools/extensions/pyspecific.py
#   https://github.com/dabeaz/curio/blob/master/docs/customization.py
#   https://github.com/aio-libs/sphinxcontrib-asyncio/blob/master/sphinxcontrib/asyncio.py

# We take a somewhat different approach, though, based on the observation that
# function properties like "classmethod", "async", "abstractmethod" can be
# mixed and matched, so the the classic sphinx approach of defining different
# directives for all of these quickly becomes cumbersome. Instead, we override
# the ordinary function & method directives to add options corresponding to
# these different properties, and override the autofunction and automethod
# directives to sniff for these properties.

# TODO:
# - figure out why properties aren't handled correctly (e.g. an abstractmethod
#   property doesn't get tagged with abstractmethod; I suspect we aren't
#   handling it at all)

import inspect
import async_generator

from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.domains.python import PyModulelevel, PyClassmember
from sphinx.ext.autodoc import (
    FunctionDocumenter, MethodDocumenter, ClassLevelDocumenter,
)

extended_function_option_spec = {
    "async": directives.flag,
    "decorator": directives.flag,
    "with": directives.unchanged,
    "async-with": directives.unchanged,
}

extended_method_option_spec = {
    **extended_function_option_spec,
    "abstractmethod": directives.flag,
    "staticmethod": directives.flag,
    "classmethod": directives.flag,
    "property": directives.flag,
}

class ExtendedCallableMixin:
    def needs_arglist(self):
        if "property" in self.options:
            return False
        if "decorator" in self.options or self.objtype == "decorator":
            return False
        return True

    def get_signature_prefix(self, sig):
        ret = ""
        if "abstractmethod" in self.options:
            ret += "abstractmethod "
        # objtype checks are for backwards compatibility, to support
        #   .. staticmethod::
        # in addition to
        #   .. method::
        #      :staticmethod:
        if "staticmethod" in self.options or self.objtype == "staticmethod":
            ret += "staticmethod "
        if "classmethod" in self.options or self.objtype == "classmethod":
            ret += "classmethod "
        if "property" in self.options:
            ret += "property "
        if "with" in self.options:
            ret += "with "
        if "async-with" in self.options:
            ret += "async with "
        if "async" in self.options:
            ret += "await "
        return ret

    def handle_signature(self, sig, signode):
        ret = super().handle_signature(sig, signode)
        if "decorator" in self.options or self.objtype == "decorator":
            signode.insert(0, addnodes.desc_addname("@", "@"))
        for optname in ["with", "async-with"]:
            if self.options.get(optname, "").strip():
                # for some reason a regular space here gets stripped, so we
                # use U+00A0 NO-BREAK SPACE
                s = "\u00A0as {}".format(self.options[optname])
                signode += addnodes.desc_annotation(s, s)
        return ret

class ExtendedPyFunction(ExtendedCallableMixin, PyModulelevel):
    option_spec = {
        **PyModulelevel.option_spec,
        **extended_function_option_spec,
    }

class ExtendedPyMethod(ExtendedCallableMixin, PyClassmember):
    option_spec = {
        **PyClassmember.option_spec,
        **extended_method_option_spec,
    }

def sniff_options(obj):
    options = set()
    async_gen = False
    # We walk the __wrapped__ chain to collect properties.
    #
    # If something sniffs as *both* an async generator *and* a coroutine, then
    # it's probably an async_generator-style async_generator (since they wrap
    # a coroutine, but are not a coroutine).
    while True:
        if getattr(obj, "__isabstractmethod__", False):
            options.add("abstractmethod")
        if isinstance(obj, classmethod):
            options.add("classmethod")
        if isinstance(obj, staticmethod):
            options.add("staticmethod")
        if isinstance(obj, property):
            options.add("property")
        if inspect.iscoroutinefunction(obj):
            options.add("async")
        if async_generator.isasyncgenfunction(obj):
            async_gen = True
        if hasattr(obj, "__wrapped__"):
            obj = obj.__wrapped__
        else:
            break
    if async_gen:
        options.discard("async")
    return options

class ExtendedFunctionDocumenter(FunctionDocumenter):
    priority = FunctionDocumenter.priority + 1
    # You can explicitly set the options in case autodetection fails
    option_spec = {
        **FunctionDocumenter.option_spec,
        **extended_function_option_spec,
    }

    def add_directive_header(self, sig):
        super().add_directive_header(sig)
        sourcename = self.get_sourcename()
        sniffed = sniff_options(self.object)
        for option in extended_function_option_spec:
            if option in self.options or option in sniffed:
                if self.options.get(option) is not None:
                    line = "   :{}: {}".format(option, self.options[option])
                else:
                    line = "   :{}:".format(option)
                self.add_line(line, sourcename)

class ExtendedMethodDocumenter(MethodDocumenter):
    priority = MethodDocumenter.priority + 1
    # You can explicitly set the options in case autodetection fails
    option_spec = {
        **MethodDocumenter.option_spec,
        **extended_method_option_spec,
    }

    def add_directive_header(self, sig):
        super().add_directive_header(sig)
        sourcename = self.get_sourcename()
        # If you have a classmethod or staticmethod, then
        #
        #   Class.__dict__["name"]
        #
        # returns the classmethod/staticmethod object, but
        #
        #   getattr(Class, "name")
        #
        # returns a regular function. We want to detect
        # classmethod/staticmethod, so we need to go through __dict__.
        obj = self.parent.__dict__.get(self.object_name)
        sniffed = sniff_options(obj)
        for option in extended_method_option_spec:
            if option in self.options or option in sniffed:
                self.add_line("   :{}:".format(option), sourcename)

    def import_object(self):
        # MethodDocumenter overrides import_object to do some sniffing in
        # addition to just importing. But we do our own sniffing and just want
        # the import, so we un-override it. (This also means we lose the
        # default behavior of putting classmethods and staticmethods earlier
        # in the display ordering. I don't really mind; I figure if I want
        # them to come first I can just put them first myself...)
        return ClassLevelDocumenter.import_object(self)

################################################################
# Register everything
################################################################

def setup(app):
    app.add_directive_to_domain('py', 'function', ExtendedPyFunction)
    app.add_directive_to_domain('py', 'method', ExtendedPyMethod)
    app.add_directive_to_domain('py', 'classmethod', ExtendedPyMethod)
    app.add_directive_to_domain('py', 'staticmethod', ExtendedPyMethod)
    app.add_directive_to_domain('py', 'decorator', ExtendedPyMethod)

    # We're overriding these on purpose, so disable the warning about it
    del directives._directives["autofunction"]
    del directives._directives["automethod"]
    app.add_autodocumenter(ExtendedFunctionDocumenter)
    app.add_autodocumenter(ExtendedMethodDocumenter)
    return {'version': '0.1', 'parallel_read_safe': True}
