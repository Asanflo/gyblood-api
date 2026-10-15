"""Format d'erreur unique : { "code": "...", "message": "...", "details": {...} }.

Le client MAUI affiche `message` tel quel à l'utilisateur (ApiExceptionExtensions.ToUserMessage).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("gyblood")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "details": details}


_HTTP_MESSAGES = {
    401: ("UNAUTHENTICATED", "Authentification requise."),
    403: ("FORBIDDEN", "Action non autorisée."),
    404: ("NOT_FOUND", "Ressource introuvable."),
    405: ("METHOD_NOT_ALLOWED", "Méthode non autorisée."),
    413: ("PAYLOAD_TOO_LARGE", "Fichier trop volumineux."),
}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_MESSAGES.get(exc.status_code, ("HTTP_ERROR", "Une erreur est survenue."))
        return JSONResponse(status_code=exc.status_code, content=_body(code, message), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = {".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]): err["msg"] for err in exc.errors()}
        return JSONResponse(
            status_code=422,
            content=_body("VALIDATION_ERROR", "Les informations saisies sont invalides.", details),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Erreur non gérée", exc_info=exc)
        return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", "Une erreur est survenue. Réessayez dans un instant."))
