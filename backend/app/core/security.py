"""
InboundCheck - Security & Authentication Dependency
===================================================
Validates Supabase JWT Bearer tokens and extracts authenticated tenant identity.
Enforces strict JWT signature and expiration verification against Supabase Auth public keys / secrets.
Fails closed with HTTP 401 on missing, expired, or invalid tokens.
"""

from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, status
import logging
import jwt
from jwt import PyJWKClient, ExpiredSignatureError, InvalidTokenError

from app.core.config import settings
from app.services.supabase_client import supabase_service

logger = logging.getLogger("SecurityAuth")

# Cached JWKS client instance
_jwks_client: Optional[PyJWKClient] = None
_jwks_url: Optional[str] = None


def _get_jwks_client() -> Optional[PyJWKClient]:
    global _jwks_client, _jwks_url
    if not settings.SUPABASE_URL or "placeholder" in settings.SUPABASE_URL:
        return None

    target_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
    if _jwks_client is None or _jwks_url != target_url:
        _jwks_url = target_url
        _jwks_client = PyJWKClient(target_url, cache_jwk_set=True, lifespan=3600)
    return _jwks_client


def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """
    Cryptographically verify Supabase JWT signature and expiration.
    Supports asymmetric JWKS (RS256/ES256) and symmetric (HS256) secrets.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as e:
        logger.warning(f"Malformed JWT header: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token"
        )

    alg = unverified_header.get("alg", "HS256")
    kid = unverified_header.get("kid")

    # 1. Asymmetric verification via Supabase JWKS (RS256 / ES256)
    if alg in ["RS256", "ES256"] or kid:
        jwks_client = _get_jwks_client()
        if jwks_client:
            try:
                signing_key = jwks_client.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=[alg],
                    options={"verify_exp": True, "verify_signature": True, "verify_aud": False}
                )
                return payload
            except ExpiredSignatureError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication token has expired"
                )
            except InvalidTokenError as e:
                logger.warning(f"JWKS signature verification failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid authentication token signature: {str(e)}"
                )
            except Exception as e:
                logger.warning(f"JWKS key resolution error: {e}")

    # 2. Symmetric verification via SUPABASE_JWT_SECRET or Supabase service keys (HS256)
    secret_candidates = [
        getattr(settings, "SUPABASE_JWT_SECRET", None),
        settings.SUPABASE_SERVICE_ROLE_KEY,
        settings.SUPABASE_KEY
    ]
    for secret in secret_candidates:
        if secret and len(secret) > 0 and "placeholder" not in secret:
            try:
                payload = jwt.decode(
                    token,
                    secret,
                    algorithms=["HS256"],
                    options={"verify_exp": True, "verify_signature": True, "verify_aud": False}
                )
                return payload
            except ExpiredSignatureError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication token has expired"
                )
            except InvalidTokenError:
                continue

    # 3. Verification via Supabase GoTrue Auth API (checks server-side public keys & revocation)
    if supabase_service.is_connected and supabase_service._client:
        try:
            user_res = supabase_service._client.auth.get_user(token)
            if user_res and user_res.user and user_res.user.id:
                return {"sub": str(user_res.user.id)}
        except Exception as e:
            logger.debug(f"Supabase auth API verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token"
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not verify token signature against Supabase Auth public keys or secrets"
    )


async def get_current_user_id(
    authorization: Optional[str] = Header(None)
) -> str:
    """
    Extract and cryptographically verify authenticated user_id from Authorization Bearer JWT.
    Fails closed if the token is missing, expired, or invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token."
        )

    token = authorization.split("Bearer ", 1)[1].strip()
    if not token or token == "placeholder":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or empty authentication Bearer token."
        )

    payload = verify_supabase_jwt(token)
    user_id = payload.get("sub") or payload.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token does not contain a valid user identity claim."
        )

    return str(user_id)
