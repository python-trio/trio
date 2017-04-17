from types import CodeType

# Has to be a string :-(
sentinel = "_unique_name"

def f():
    print(locals())

# code(argcount, kwonlyargcount, nlocals, stacksize, flags, codestring,
#       constants, names, varnames, filename, name, firstlineno,
#       lnotab[, freevars[, cellvars]])
new_code = CodeType(
    f.__code__.co_argcount,
    f.__code__.co_kwonlyargcount + 1,
    f.__code__.co_nlocals + 1,
    f.__code__.co_stacksize,
    f.__code__.co_flags,
    f.__code__.co_code,
    f.__code__.co_consts,
    f.__code__.co_names,
    f.__code__.co_varnames + (sentinel,),
    f.__code__.co_filename,
    f.__code__.co_name,
    f.__code__.co_firstlineno,
    f.__code__.co_lnotab,
    f.__code__.co_freevars,
    f.__code__.co_cellvars,
)

f.__code__ = new_code
f.__kwdefaults__ = {sentinel: "fdsa"}

f()
