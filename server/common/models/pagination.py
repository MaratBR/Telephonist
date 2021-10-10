import math
from enum import Enum
from typing import Type, Optional, Generic, List, TypeVar

from beanie import Document
from beanie.odm.enums import SortDirection
from fastapi.params import Depends, Query
from pydantic import BaseModel
from pydantic.generics import GenericModel


class Pagination:
    def __init__(self,
                 page: int = Query(1, gt=0),
                 page_size: int = Query(20, gt=4)):
        self.page = page
        self.page_size = page_size


class OrderingDirection(str, Enum):
    ASC = 'asc'
    DESC = 'desc'


TPaginationItem = TypeVar('TPaginationItem')


class PaginationResult(GenericModel, Generic[TPaginationItem]):
    result: List[TPaginationItem]
    page: int
    page_size: int
    total: int
    pages_total: int
    ordered_by: str
    order: OrderingDirection


class PaginationWithOrdering(Pagination):
    def __init__(self,
                 page: int = Query(1, gt=0),
                 page_size: int = Query(20, gt=4),
                 field: Optional[str] = Query(None),
                 order: Optional[OrderingDirection] = Query(OrderingDirection.DESC)):
        super(PaginationWithOrdering, self).__init__(page, page_size)
        self.field = field
        self.order = order

    @classmethod
    def from_choices(cls, choices: List[str]):
        FieldEnum = Enum('FieldEnum', {k: k for k in choices})  # noqa

        class NewType(cls):
            def __init__(self,
                         page: int = Query(1, gt=0),
                         page_size: int = Query(20, gt=4),
                         field: Optional[FieldEnum] = Query(None),
                         order: Optional[OrderingDirection] = Query(OrderingDirection.DESC)):
                if isinstance(field, Enum):
                    field = str(field)[len(type(field).__name__) + 1:]
                super(NewType, self).__init__(page, page_size, field, order)

        return Depends(NewType)

    async def paginate(self, cls: Type[Document], project: Optional[Type[BaseModel]] = None):
        q = cls.find()
        order = self.order or OrderingDirection.ASC
        ordered_by = self.field or '_id'
        print(ordered_by)
        q = q.sort(
            (ordered_by, SortDirection.DESCENDING if order == OrderingDirection.DESC else SortDirection.ASCENDING))
        total = await q.count()
        q = q.skip((self.page - 1) * self.page_size).limit(self.page_size)
        if project:
            q = q.project(project)
        items = await q.to_list()

        return PaginationResult(
            result=items,
            page=self.page,
            page_size=self.page_size,
            total=total,
            pages_total=math.ceil(total / self.page_size),
            ordered_by=ordered_by,
            order=order
        )
