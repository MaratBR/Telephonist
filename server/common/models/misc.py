from beanie import PydanticObjectId
from pydantic import BaseModel, Field


class IdProjection(BaseModel):
    id: PydanticObjectId = Field(alias='_id')
