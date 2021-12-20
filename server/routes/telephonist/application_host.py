from datetime import datetime, timedelta
from typing import Optional

import fastapi
from fastapi import Body, HTTPException, Depends
from pydantic import BaseModel
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

from server.internal.auth.dependencies import UserToken
from server.models.auth import TokenModel
from server.models.telephonist import ApplicationHost, LocalConfig, HostSoftware, OneTimeSecurityCode, Server

router = fastapi.APIRouter(tags=['app-host'], prefix='/app-host')


async def application_host() -> ApplicationHost:
    host = await ApplicationHost.get(token.subject.oid)
    if host is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return host


class HostedApplication(BaseModel):
    name: str


class HostUpdate(BaseModel):
    local_config: LocalConfig
    software: Optional[HostSoftware]


def apply_host_update(host: ApplicationHost, update: HostUpdate):
    if update.software:
        host.software = update.software

    if update.local_config:
        host.local_config = update.local_config
        host.local_config_rev = datetime.now()


@router.post('/update')
async def host_update(
        host: ApplicationHost = Depends(application_host),
        body: HostUpdate = Body(...)
):
    apply_host_update(host, body)
    await host.save_changes()


class SRCreateCodeRequest(BaseModel):
    created_by: str


class SRAcceptedResponse(BaseModel):
    code: str
    expires_at: datetime


@router.post('/self-register', response_model=SRAcceptedResponse)
async def self_registration(body: SRCreateCodeRequest, request: Request):
    code = await OneTimeSecurityCode.new('host_confirm', body.created_by, request.client.host)
    return dict(code=code.id, expires_at=code.expires_at)


class SelfRegistrationCodeRequest(BaseModel):
    code: str


@router.get('/self-register/{code}')
async def get_self_registration_code(code: str):
    code = await OneTimeSecurityCode.get_valid_code('host_confirm', code)
    if code is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Code does not exist or invalid')
    return code


@router.post('/self-register/{code}/confirm')
async def confirm_self_registration(
        code: str,
        user_token: TokenModel = UserToken()
):
    code = await OneTimeSecurityCode.get_valid_code('host_confirm', code)
    if code is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Code is invalid')
    code.expires_at = datetime.now() + timedelta(minutes=30)
    code.confirmed = True
    await code.save()
    # TODO log
    return {'expires_at': code.expires_at}


class FinishSelfRegistrationRequest(SelfRegistrationCodeRequest):
    name: str
    update: Optional[HostUpdate]


@router.post('/self-register/finish')
async def finish_self_registration(
        body: FinishSelfRegistrationRequest,
        request: Request
):
    code = await OneTimeSecurityCode.get_valid_code('host_confirm', body.code)
    if code is None or not code.confirmed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Code does not exist, expired or wasn\'t confirmed yet')
    await Server.report_server(request.client)
    host = ApplicationHost(name=body.name, server_ip=request.client.host)
    if body.update:
        apply_host_update(host, body.update)
    await host.save()
    await code.delete()
    # TODO более подробная информация
    return JSONResponse({'_id': str(host.id)}, status_code=status.HTTP_201_CREATED)


class AppHostToken(BaseModel):
    token: str


@router.post('/token', name='Get application-host access token')
async def authenticate_host(body: AppHostToken):
    host = await ApplicationHost.find_one(ApplicationHost.token == body.token)
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'App host with given could\'nt be found')
    token = host.create_token(lifetime=timedelta(hours=2))
    return {'token': token.encode()}
