import math
from enum import Enum
from typing import Type, Optional, Generic, List, TypeVar, Dict, Any, Union

from beanie import Document
from beanie.odm.enums import SortDirection
from fastapi.params import Depends, Query
from pydantic import BaseModel
from pydantic.generics import GenericModel


class SimplePagination:
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


class Pagination(SimplePagination):
    def __init__(self,
                 page: int = Query(1, gt=0),
                 page_size: int = Query(20, gt=4),
                 field: Optional[str] = Query(None),
                 order: Optional[OrderingDirection] = Query(OrderingDirection.DESC)):
        super(Pagination, self).__init__(page, page_size)
        self.field = field
        self.order = order

    @classmethod
    def from_choices(cls, order_choices: List[str]):
        if '_id' not in order_choices:
            order_choices.append('_id')
        order_choices.sort()
        dictionary = {
            (k[1:] if k.startswith('_') else k): k for k in order_choices
        }
        field_enum = Enum(f'FieldEnum_{"_".join(dictionary.keys())}', dictionary)  # noqa

        class NewType(cls):
            def __init__(self,
                         page: int = Query(1, gt=0),
                         page_size: int = Query(20, gt=4),
                         field: Optional[field_enum] = Query(field_enum.id),
                         order: Optional[OrderingDirection] = Query(OrderingDirection.DESC)):
                field = field.value
                super(NewType, self).__init__(page, page_size, field, order)

        return Depends(NewType)

    async def paginate(
            self,
            cls: Type[Document],
            project: Optional[Type[BaseModel]] = None,
            filter_condition: Optional[Union[Dict[str, Any], List[Dict[str, Any]], List[bool]]] = None
    ):
        if filter_condition:
            q = cls.find(*filter_condition) if isinstance(filter_condition, list) else cls.find(filter_condition)
        else:
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
