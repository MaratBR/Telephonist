from datetime import date, datetime
from typing import Optional

import pymongo

from server.common.models import AppBaseModel, BaseDocument
from server.database.registry import register_model


class CountersValue(AppBaseModel):
    year: int = 0
    month: int = 0
    week: int = 0
    day: int = 0


class Periods(AppBaseModel):
    year: str
    month: str
    week: str
    day: str

    def __init__(self, d: date):
        super(Periods, self).__init__(
            year=d.strftime("Y%Y"),
            month=d.strftime("M%Y%m"),
            week=d.strftime("W%Y%W"),
            day=d.strftime("D%Y%m%d"),
        )

    def __contains__(self, item):
        return item in list(self)

    def __iter__(self):
        yield from [self.year, self.month, self.week, self.day]


class Counters(AppBaseModel):
    periods: Periods
    values: dict[str, CountersValue]


@register_model
class Counter(BaseDocument):
    id: str
    value: int
    period: str
    subject: str

    @classmethod
    async def get_counters(cls, subjects: set[str]) -> Counters:
        subjects = {s if isinstance(s, str) else ":".join(s) for s in subjects}
        periods = cls.get_current_periods()
        counters = await cls.find(
            {
                "subject": {"$in": list(subjects)},
                "period": {"$in": list(periods)},
            }
        ).to_list()
        result: dict[str, CountersValue] = {}
        for c in counters:
            cv = result.get(c.subject)
            if cv is None:
                cv = CountersValue()
                result[c.subject] = cv
            if c.period.startswith("Y"):
                cv.year = c.value
            elif c.period.startswith("M"):
                cv.month = c.value
            elif c.period.startswith("W"):
                cv.week = c.value
            elif c.period.startswith("D"):
                cv.day = c.value

        for s in subjects:
            if s not in result:
                result[s] = CountersValue()

        return Counters(values=result, periods=periods)

    @classmethod
    async def get_counter(cls, subject: str) -> CountersValue:
        counters = await cls.get_counters({subject})
        return counters.values[subject]

    @classmethod
    async def inc_counter(
        cls, subject: str, value: int, periods: Optional[set[str]] = None
    ):
        if value == 0:
            return
        periods = periods or set(cls.get_current_periods())
        counters = await cls.find(
            {"period": {"$in": list(periods)}, "subject": subject}
        ).to_list()
        existing_periods = set()
        for c in counters:
            existing_periods.add(c.period)
        new_periods = periods.difference(existing_periods)
        if len(new_periods) > 0:
            await Counter.insert_many(
                [
                    Counter(
                        id=f"{subject}/{period}",
                        subject=subject,
                        period=period,
                        value=value,
                    )
                    for period in new_periods
                ]
            )
        await cls.find(
            {"period": {"$in": list(existing_periods)}, "subject": subject}
        ).inc({"value": value})

    @staticmethod
    def get_current_periods():
        return Periods(datetime.now().date())

    class Collection:
        indexes = [
            pymongo.IndexModel(
                [
                    ("period", pymongo.DESCENDING),
                    ("subject", pymongo.ASCENDING),
                ],
                unique=True,
            )
        ]
