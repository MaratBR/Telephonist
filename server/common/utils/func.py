import types
from collections import OrderedDict


def update_di_wrapper(wrapper, wrapped):
    wrapper_code: types.CodeType = wrapper.__code__
    wrapped_code: types.CodeType = wrapper.__code__

    new_code = types.CodeType(
        wrapper_code.co_argcount + wrapped_code.co_argcount,
        wrapper_code.co_posonlyargcount + wrapped_code.co_posonlyargcount,
        wrapper_code.co_kwonlyargcount + wrapped_code.co_kwonlyargcount,
        wrapper_code.co_nlocals,
        wrapper_code.co_stacksize,
        wrapper_code.co_flags,
        wrapper_code.co_code,
        wrapper_code.co_consts,
        wrapper_code.co_names,
        wrapper_code.co_varnames,
        wrapper_code.co_filename,
        wrapper_code.co_name,
        wrapper_code.co_firstlineno,
        wrapper_code.co_lnotab,
        wrapper_code.co_freevars,
        wrapper_code.co_cellvars
    )

    fn = types.FunctionType(new_code, wrapper.__globals__, wrapper_code.co_name)
    annotations = OrderedDict(wrapper.__annotations__)
    for k, v in wrapped.__annotations__.items():
        if k in annotations:
            raise ValueError('functions have conflicting arguments: ' + k)
        annotations[k] = v

    fn.__annotations__ = dict(annotations.items())
    fn.__defaults__ = (wrapper.__defaults__ or ()) + (wrapped.__defaults__ or ())
    return fn
