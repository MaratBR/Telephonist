import inspect
from typing import Any

from server.internal.auth.dependencies import UserToken


def authorize(fn: Any):
    if callable(fn):
        return _authorize(fn, UserToken())
    else:
        def decorator(fn_):
            return _authorize(fn_, fn)
        return decorator


def _authorize(fn, annotation):
    def new_route_function(*args, __token__, **kwargs):
        return fn(*args, **kwargs)

    signature = inspect.signature(fn)
    parameters = list(signature.parameters.values())
    if any(p.name == '__token__' for p in parameters):
        # TODO warning?
        return fn
    parameters.append(inspect.Parameter('__token__', inspect.Parameter.KEYWORD_ONLY, annotation=annotation))
    signature = signature.replace(parameters=parameters)
    setattr(new_route_function, '__signature__', signature)
    new_route_function.__name__ = fn.__name__
    setattr(fn, '__authorized_callable__', new_route_function)
