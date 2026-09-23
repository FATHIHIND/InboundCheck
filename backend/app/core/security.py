"""
InboundCheck - Security & Authentication Dependency
===================================================
Validates Supabase JWT Bearer tokens and extracts authenticated tenant identity.
Enforces strict cryptographic verification against Supabase Auth public keys / secrets.
Fails closed with HTTP 401 on missing, expired, forged, or invalid tokens.

CRITICAL SECURITY DIRECTIVES:
- Only SUPABASE_JWT_SECRET is accepted for symmetric HS256 tokens.
- SUPABASE_KEY (public anon key) is NEVER used as a signing secret.
- SUPABASE_SERVICE_ROLE_KEY is NEVER used as a signing secret.
- RS256/ES256 asymmetric verification uses cached Supabase JWKS with bounded timeout.
- Strict algorithm allowlist: ["RS256", "ES256", "HS256"].
- Mandatory claims validation: exp, nbf, aud="authenticated", role="authenticated", non-empty sub.
- Opaque error responses fail closed without leaking internal details.
- Never log raw JWTs, headers, keys, or secrets.
"""

from typing import Optional, Dict, Any, Set
from fastapi import Header, HTTPException, status
import logging
import jwt
from jwt import (
    PyJWKClient,
    ExpiredSignatureError,
    InvalidTokenError,
    DecodeError,
    InvalidSignatureError,
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    ImmatureSignatureError,
)

from app.core.config import settings

logger = logging.getLogger("SecurityAuth")

# Strict algorithm allowlist - reject "none", HS384, HS512, RS384, RS512, ES384, ES512, and unknown algs
ALLOWED_ALGORITHMS: Set[str] = {"RS256", "ES256", "HS256"}

# Opaque client error messages
AUTH_ERROR_DETAIL = "Invalid or expired authentication token"
AUTH_REQUIRED_DETAIL = "Authentication required. Please provide a valid Bearer token."

# Cached JWKS client instance with bounded timeout and safe cache lifespan
_jwks_client: Optional[PyJWKClient] = None
_jwks_url: Optional[str] = None


def _get_jwks_client() -> Optional[PyJWKClient]:
    """Retrieve or initialize cached PyJWKClient for asymmetric Supabase verification."""
    global _jwks_client, _jwks_url
    if not settings.SUPABASE_URL or "placeholder" in settings.SUPABASE_URL:
        return None

    target_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
    if _jwks_client is None or _jwks_url != target_url:
        _jwks_url = target_url
        _jwks_client = PyJWKClient(target_url, cache_jwk_set=True, lifespan=3600, timeout=5)
    return _jwks_client


def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """
    Cryptographically verify Supabase JWT signature, algorithm, and claims.
    
    Pipeline:
    1. Parse unverified header ONLY to extract algorithm.
    2. Enforce strict algorithm allowlist (RS256, ES256, HS256).
    3. Execute cryptographic signature verification against legitimate signing key:
       - Asymmetric (RS256/ES256): Supabase JWKS public key.
       - Symmetric (HS256): SUPABASE_JWT_SECRET ONLY. Never anon key, never service-role key.
    4. Enforce mandatory claims:
       - exp: token must not be expired.
       - nbf: token must be valid at current time.
       - aud: must match configured audience (default 'authenticated').
       - role: must equal 'authenticated' (rejects 'anon' and 'service_role').
       - sub: must be a non-empty valid user identifier.
       - iss: if present, must match expected Supabase issuer.
    5. Fail closed with opaque HTTP 401 on any failure.
    """
    if not token or not isinstance(token, str) or len(token.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_REQUIRED_DETAIL
        )

    # 1. Inspect unverified header strictly for algorithm identification
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception:
        logger.warning("Rejected token with malformed unverified header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )

    alg = unverified_header.get("alg")
    if not alg or alg not in ALLOWED_ALGORITHMS:
        logger.warning("Rejected token with missing, 'none', or unapproved algorithm")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )

    # 2. Cryptographic signature verification
    expected_audience = getattr(settings, "SUPABASE_JWT_AUDIENCE", "authenticated") or "authenticated"
    decode_options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_nbf": True,
        "verify_aud": True,
    }

    payload: Dict[str, Any] = {}

    if alg in ["RS256", "ES256"]:
        # Asymmetric verification via Supabase JWKS
        jwks_client = _get_jwks_client()
        if not jwks_client:
            logger.warning("JWKS client not available for asymmetric verification")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience=expected_audience,
                options=decode_options,
            )
        except ExpiredSignatureError:
            logger.info("Rejected expired asymmetric authentication token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )
        except (InvalidSignatureError, DecodeError, InvalidAlgorithmError, InvalidAudienceError, InvalidIssuerError, ImmatureSignatureError, InvalidTokenError):
            logger.warning("JWKS signature or claims verification failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )
        except Exception:
            logger.warning("Unexpected error during JWKS verification")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )

    elif alg == "HS256":
        # Symmetric verification via SUPABASE_JWT_SECRET ONLY
        # CRITICAL: SUPABASE_KEY and SUPABASE_SERVICE_ROLE_KEY are strictly forbidden here.
        jwt_secret = getattr(settings, "SUPABASE_JWT_SECRET", None)
        if not jwt_secret or not isinstance(jwt_secret, str) or len(jwt_secret.strip()) == 0 or "placeholder" in jwt_secret:
            logger.warning("Rejected HS256 token: SUPABASE_JWT_SECRET is unconfigured or placeholder")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )

        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience=expected_audience,
                options=decode_options,
            )
        except ExpiredSignatureError:
            logger.info("Rejected expired symmetric authentication token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )
        except (InvalidSignatureError, DecodeError, InvalidAlgorithmError, InvalidAudienceError, InvalidIssuerError, ImmatureSignatureError, InvalidTokenError):
            logger.warning("HMAC signature or claims verification failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )
        except Exception:
            logger.warning("Unexpected error during HMAC verification")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )

    # 3. Mandatory claims enforcement
    # Require expiration claim
    if "exp" not in payload:
        logger.warning("Rejected token missing required 'exp' claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )

    # Require subject claim (user identity)
    sub = payload.get("sub") or payload.get("user_id")
    if not sub or not isinstance(sub, str) or len(sub.strip()) == 0:
        logger.warning("Rejected token with missing, non-string, or empty 'sub' claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )

    # Require audience claim
    aud = payload.get("aud")
    if not aud:
        logger.warning("Rejected token missing required 'aud' claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )
    if isinstance(aud, list):
        if expected_audience not in aud:
            logger.warning("Rejected token with mismatched audience in claim list")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )
    elif aud != expected_audience:
        logger.warning("Rejected token with mismatched audience claim string")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )

    # Require role claim == 'authenticated' (strictly reject 'anon' and 'service_role')
    role = payload.get("role")
    if not role or role != "authenticated":
        logger.warning("Rejected token: role claim is not 'authenticated'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )

    # Validate issuer when present
    iss = payload.get("iss")
    if iss:
        supabase_url = getattr(settings, "SUPABASE_URL", "")
        expected_issuers = ["supabase"]
        if supabase_url and "placeholder" not in supabase_url:
            expected_issuers.append(f"{supabase_url.rstrip('/')}/auth/v1")
        if iss not in expected_issuers:
            logger.warning("Rejected token with untrusted issuer claim")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_ERROR_DETAIL
            )

    return payload


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
            detail=AUTH_REQUIRED_DETAIL
        )

    token = authorization.split("Bearer ", 1)[1].strip()
    if not token or token == "placeholder":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_REQUIRED_DETAIL
        )

    payload = verify_supabase_jwt(token)
    user_id = payload.get("sub") or payload.get("user_id")

    if not user_id or not isinstance(user_id, str) or len(str(user_id).strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_ERROR_DETAIL
        )

    return str(user_id).strip()

