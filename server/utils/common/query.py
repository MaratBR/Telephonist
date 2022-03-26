from typing import Type, TypeVar

from fastapi import Depends, HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from server.common.models import AppBaseModel

T = TypeVar("T", bound=AppBaseModel)


def Querydict(model: Type[T]) -> T:  # noqa
    def query_dict_dependency(request: Request):
        try:
            return model(**request.query_params)
        except ValidationError as err:
            errors = err.errors()
            for e in errors:
                e["loc"] = ("query",) + e["loc"]
            raise HTTPException(422, errors)

    return Depends(query_dict_dependency)
