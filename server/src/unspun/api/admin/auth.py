from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request

from unspun.core.config import Settings, get_settings


@lru_cache
def _jwk_client(domain: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"https://{domain}/cdn-cgi/access/certs", timeout=5)


def require_admin_identity(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> str:
    if (
        settings.admin_local_preview
        and request.client is not None
        and request.client.host in {"127.0.0.1", "::1"}
    ):
        return "local-preview"

    domain = settings.access_team_domain.lower().strip()
    audience = settings.access_audience.strip()
    if not domain.endswith(".cloudflareaccess.com") or "/" in domain or not audience:
        raise HTTPException(status_code=503, detail="Admin Access verification is not configured")

    assertion = request.headers.get("Cf-Access-Jwt-Assertion")
    if not assertion:
        raise HTTPException(status_code=401, detail="Access identity required")
    try:
        key = _jwk_client(domain).get_signing_key_from_jwt(assertion).key
        claims = jwt.decode(
            assertion,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"https://{domain}",
            options={"require": ["aud", "exp", "iat", "iss", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="Invalid Access identity") from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="Access verification unavailable") from error
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="Invalid Access identity")
    return subject
