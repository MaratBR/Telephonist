import json
from datetime import datetime

import pytest
from pydantic import BaseModel, validator

from server.models.common import convert_to_utc


@pytest.mark.parametrize(
    "desc",
    [
        ("2022-02-15T21:01:43+00:00", "2022-02-15T21:01:43+00:00"),
        ("2022-02-15T21:01:43+07:00", "2022-02-15T14:01:43+00:00"),
    ],
)
def test_convert_to_utc(desc):
    local_s, utc_s = desc
    utc = datetime.fromisoformat(utc_s)
    local = datetime.fromisoformat(local_s)
    assert utc == convert_to_utc(local)

    class Model(BaseModel):
        value: datetime
        _value_validator = validator("value", allow_reuse=True)(convert_to_utc)

    m = Model(value=local)
    assert m.value == utc
    assert json.loads(m.json())["value"] == utc_s
