import jsonschema
from jsonschema.protocols import Validator  # type: ignore

from server.settings import settings

try:
    JSON_SCHEMA_VALIDATOR: Validator = getattr(
        __import__(settings.jsonschema_validator.rsplit(".", 1)[0]),
        settings.jsonschema_validator.rsplit(".", 1)[1],
    )
except (ImportError, AttributeError, KeyError, AssertionError) as exc:
    raise RuntimeError(
        "Failed to load json schema validator, make sure Settings class has"
        " jsonschema_validator value set to a valid import path of the Validator"
        f" protocol. Exception that occured: \n {exc}"
    )


def is_valid_jsonschema(schema):
    try:
        jsonschema.validate(schema, JSON_SCHEMA_VALIDATOR.META_SCHEMA)
        return True
    except jsonschema.ValidationError:
        return False
