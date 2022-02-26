"""
[4300, 4499] - http errors equivalents (i.e. 4422 wsc = 422 http)
5XX http - 1011 wsc
"""
# with

WSC_UNAUTHORIZED = 4001
WSC_CONFLICT = 4009
WSC_NOT_FOUND = 4004
WSC_INVALID = 4000
WSC_INTERNAL_ERROR = 1011
WSC_I_AM_CONFUSED = 4998


_mapped_codes = {500: WSC_INTERNAL_ERROR, 400: WSC_INVALID}


def map_http_to_wsc(http_status: int):
    if 200 <= http_status < 300:
        return 1000
    if 300 <= http_status < 500:
        return 4000 + http_status
    if 500 <= http_status < 600:
        return WSC_INTERNAL_ERROR
    return WSC_I_AM_CONFUSED
