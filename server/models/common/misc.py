import re

from beanie import PydanticObjectId
from pydantic import BaseModel, Field, constr


class IdProjection(BaseModel):
    id: PydanticObjectId = Field(alias="_id")


Identifier = constr(regex=r"^[\d\w%^$#&\-]+$")
