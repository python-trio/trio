# Inspirations:
#   https://github.com/python/cpython/blob/master/Doc/tools/extensions/pyspecific.py
#   https://github.com/dabeaz/curio/blob/master/docs/customization.py
#   https://github.com/aio-libs/sphinxcontrib-asyncio/blob/master/sphinxcontrib/asyncio.py

# Parts of this derived from the CPython source code, under the terms of the
# PSF License, which requires the following notice:
#   Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
#   2011, 2012, 2013, 2014, 2015, 2016, 2017 Python Software Foundation; All
#   Rights Reserved

import inspect

from sphinx import addnodes
from sphinx.domains.python import PyModulelevel, PyClassmember
from sphinx.ext.autodoc import FunctionDocumenter, MethodDocumenter

class ExtendedCallableMixin:
    def needs_arglist(self):
        if "property" in self.options:
            return False
        else:
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
        if "async" in self.options:
            ret += "await "
        return ret

extended_function_option_spec = {
    "async": directives.flag,
}

extended_method_option_spec = {
    "abstractmethod": directives.flag,
    "staticmethod": directives.flag,
    "classmethod": directives.flag,
    "property": directives.flag,
    "async": directives.flag,
}

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
    # Peek through any well-behaved decorators
    while hasattr(obj, "__wrapped__"):
        obj = obj.__wrapped__
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
                self.add_line('   :{}:'.format(option), sourcename)

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
        sniffed = sniff_options(self.object)
        for option in extended_method_option_spec:
            if option in self.options or option in sniffed:
                self.add_line('   :{}:'.format(option), sourcename)

################################################################
# Async functions and methods
################################################################

class PyAsyncMixin:
    def handle_signature(self, sig, signode):
        ret = super(PyAsyncMixin, self).handle_signature(sig, signode)
        signode.insert(0, addnodes.desc_annotation('await ', 'await '))
        return ret

class PyAsyncFunction(PyAsyncMixin, PyModulelevel):
    def run(self):
        self.name = 'py:function'
        return PyModulelevel.run(self)

class PyAsyncMethod(PyAsyncMixin, PyClassmember):
    def run(self):
        print(self)
        self.name = 'py:method'
        return PyClassmember.run(self)

class AsyncDocumenterMixin:
    @classmethod
    def can_document_member(cls, member, membername, isattr, parent):
        print("{}.can_document_member!".format(cls))
        if not super().can_document_member(member, membername, isattr, parent):
            print("nope!")
            return False
        ret = inspect.iscoroutinefunction(member)
        print("result:", ret)
        return ret

    def add_directive_header(self, sig):
        print("add_directive_header", self, sig, self.directivetype)
        print(self.format_name())
        print(self.get_sourcename())
        return super().add_directive_header(sig)

class AsyncFunctionDocumenter(AsyncDocumenterMixin, FunctionDocumenter):
    objtype = directivetype = "asyncfunction"
    priority = FunctionDocumenter.priority + 1

class AsyncMethodDocumenter(AsyncDocumenterMixin, MethodDocumenter):
    objtype = directivetype = "asyncmethod"
    priority = 100 #MethodDocumenter.priority + 1

################################################################
# Abstract methods
################################################################

class PyAbstractMethod(PyClassmember):

    def handle_signature(self, sig, signode):
        ret = super(PyAbstractMethod, self).handle_signature(sig, signode)
        signode.insert(0, addnodes.desc_annotation('abstractmethod ',
                                                   'abstractmethod '))
        return ret

    def run(self):
        self.name = 'py:method'
        return PyClassmember.run(self)

class AbstractMethodDocumenter(MethodDocumenter):
    objtype = directivetype = "abstractmethod"
    priority = MethodDocumenter.priority + 1

    @classmethod
    def can_document_member(cls, member, membername, isattr, parent):
        if not super().can_document_member(member, membername, isattr, parent):
            return False
        return getattr(member, "__isabstractmethod__", False)

################################################################
# Register everything
################################################################

# really async, abstractmethod, classmethod, staticmethod should be attributes
# of the thing
# maybe also generator, async generator, context manager, async context
# manager
# because these can all be mixed and matched

# so we override .. function:: and .. method:: to add these attributes

# abstract classmethod await foo(...)

def setup(app):
    app.add_directive_to_domain('py', 'asyncfunction', PyAsyncFunction)
    app.add_directive_to_domain('py', 'asyncmethod', PyAsyncMethod)
    app.add_directive_to_domain('py', 'asyncclassmethod', PyAsyncMethod)
    app.add_directive_to_domain('py', 'asyncstaticmethod', PyAsyncMethod)
    app.add_directive_to_domain('py', 'abstractmethod', PyAbstractMethod)

    app.add_autodocumenter(AsyncFunctionDocumenter)
    app.add_autodocumenter(AsyncMethodDocumenter)
    app.add_autodocumenter(AbstractMethodDocumenter)
    return {'version': '0.1', 'parallel_read_safe': True}
