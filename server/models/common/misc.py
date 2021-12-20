import re

from beanie import PydanticObjectId
from pydantic import BaseModel


class IdProjection(BaseModel):
    id: PydanticObjectId


class Identifier(str):
    regex = re.compile(r'^[\d\w%^$#&\- ]+$', re.IGNORECASE)

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(
            pattern=r'^[\d\w%^$#&-]+$',
            examples=['some_identifier', 'these-are-also-allowed-%^$#&-42', 'You can also use spaces'],
        )

    @classmethod
    def validate(cls, v):
        if not isinstance(v, str):
            raise TypeError('string required')
        m = cls.regex.fullmatch(v)
        if not m:
            raise ValueError('invalid identifier format: ' + v)
        return cls(v)
