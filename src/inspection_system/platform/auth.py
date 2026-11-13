from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable
from fastapi import Depends, Header, HTTPException, Request, status
import jwt
from jwt import PyJWKClient
from .settings import Settings


@dataclass(frozen=True)
class Actor:
    subject: str
    role: str
    roles: frozenset[str] = frozenset()

    @property
    def effective_roles(self) -> frozenset[str]:
        return self.roles or frozenset({self.role})


@lru_cache(maxsize=8)
def _jwk_client(issuer: str) -> PyJWKClient:
    return PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json", timeout=5)


def actor_from_request(
    request: Request,
    authorization: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
) -> Actor:
    settings: Settings = request.app.state.settings
    if settings.auth_mode == "development":
        role = x_actor_role or "admin"
        if role not in {"admin", "operator", "reviewer", "viewer"}:
            raise HTTPException(status_code=400, detail="Unknown development role.")
        return Actor("local-development-user", role)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Bearer token required.",
                            headers={"WWW-Authenticate": "Bearer"})
    token = authorization.removeprefix("Bearer ").strip()
    try:
        signing_key = _jwk_client(settings.oidc_issuer or "").get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid bearer token.",
                            headers={"WWW-Authenticate": "Bearer"}) from exc

    app_metadata = claims.get("app_metadata")
    roles: list[str] = []
    if isinstance(app_metadata, dict):
        configured_roles = app_metadata.get("roles", [])
        if isinstance(configured_roles, list):
            roles.extend(role for role in configured_roles if isinstance(role, str))
    recognized = [role for role in roles
                  if role in {"admin", "operator", "reviewer", "viewer"}]
    if not recognized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={
                                "code": "APPLICATION_ROLE_REQUIRED",
                                "message": "No authorized application role.",
                            })
    role_order = {"viewer": 0, "operator": 1, "reviewer": 2, "admin": 3}
    role = max(recognized, key=role_order.get)
    return Actor(str(claims["sub"]), role, frozenset(recognized))


def require_roles(*allowed_roles: str) -> Callable[..., Actor]:
    def dependency(actor: Actor = Depends(actor_from_request)) -> Actor:
        if not actor.effective_roles.intersection(allowed_roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail={
                                    "code": "INSUFFICIENT_ROLE",
                                    "message": "Insufficient role.",
                                })
        return actor
    return dependency
