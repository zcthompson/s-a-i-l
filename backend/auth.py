"""Authentication utilities for S-A-I-L (Sales Analytics and Intelligence Launchpad).

Handles password hashing and JWT token generation/verification.
Auth is optional — active when the explicit SAIL_AUTH_ENABLED switch says
so; when that switch is unset, the legacy behavior applies (active when
SAIL_API_KEYS is non-empty).
"""

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import sessionmaker

from backend.config import get_settings
from backend.database import create_engine

# Import-time configuration (A-8 re-recon 2026-11-01 — moved from raw
# os.environ reads into Settings; .env is loaded before this import in
# backend/main.py, and by conftest in tests).
_app_settings = get_settings()

# JWT configuration
SECRET_KEY = _app_settings.jwt_secret

# Documented/placeholder values that have been published in repo files or docs
# (SEC-01). Any of these is accepted by no deployment: the secret is public,
# so a token signed with it is forgeable for a known username.
_PLACEHOLDER_JWT_SECRETS = frozenset(
    {
        "change-me-in-production",
        "changeme-changeme-changeme-changeme",
    }
)
# Minimum entropy bar: 32 characters (matches the documented generation
# command, `openssl rand -hex 32`).
_JWT_SECRET_MIN_LENGTH = 32


def validate_jwt_secret(secret: str) -> None:
    """Refuse to start with an empty, placeholder, or too-short JWT secret.

    Enforced at import time so a deployment cannot boot with a publicly
    documented signing key (SEC-01). Raises RuntimeError with guidance.
    """
    if not secret:
        raise RuntimeError(
            "SAIL_JWT_SECRET is not set. "
            "Set it to a random string (at least 32 characters) before starting. "
            "Example: openssl rand -hex 32"
        )
    if secret in _PLACEHOLDER_JWT_SECRETS:
        raise RuntimeError(
            "SAIL_JWT_SECRET is set to a documented placeholder value. "
            "Generate a random secret (at least 32 characters): openssl rand -hex 32"
        )
    if len(secret) < _JWT_SECRET_MIN_LENGTH:
        raise RuntimeError(
            f"SAIL_JWT_SECRET is too short ({len(secret)} characters; "
            f"minimum {_JWT_SECRET_MIN_LENGTH}). "
            "Generate a random secret: openssl rand -hex 32"
        )


validate_jwt_secret(SECRET_KEY)

_AUTH_ON_VALUES = frozenset({"1", "true", "yes", "on"})
_AUTH_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def resolve_auth_enabled(flag: str, api_keys: str) -> bool:
    """Compute the auth feature switch (A-10, operator ruling 2026-11-01).

    ``SAIL_AUTH_ENABLED`` wins when set: any of 1/true/yes/on (case-
    insensitive) enables auth, any of 0/false/no/off disables it, and any
    other value raises RuntimeError — a misconfigured switch must not
    silently fall back. When the flag is empty/unset, the legacy behavior
    applies: auth is enabled iff the API-key list is non-empty. The key
    list itself is a credential store (X-API-Key values; only consumed by
    the dept-restriction mechanism), no longer a feature switch by
    default.
    """
    value = flag.strip().lower()
    if value:
        if value in _AUTH_ON_VALUES:
            return True
        if value in _AUTH_OFF_VALUES:
            return False
        raise RuntimeError(
            f"SAIL_AUTH_ENABLED has an unrecognized value {flag!r}. "
            "Use 1/true/yes/on to enable auth or 0/false/no/off to disable it "
            "(unset falls back to the legacy rule: auth on when SAIL_API_KEYS is non-empty)."
        )
    return bool(api_keys.strip())


API_KEYS = _app_settings.api_keys
AUTH_ENABLED = resolve_auth_enabled(_app_settings.auth_enabled, API_KEYS)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = _app_settings.token_expire_minutes

# Brute force protection configuration
LOGIN_MAX_ATTEMPTS = _app_settings.login_max_attempts
LOGIN_LOCKOUT_MINUTES = _app_settings.login_lockout_minutes

# In-memory brute force tracker (bounded). A-8 re-recon 2026-11-01: the
# login tracker got its own bound name; SAIL_TRACKED_REQUESTS (which used
# to control two unrelated bounds — the other consumer, main.py's dead
# request store, is gone per A-6) still works as a fallback alias.
_login_attempts: dict[str, list] = {}  # username -> [timestamp, ...]
_max_tracked = int(os.environ.get("SAIL_LOGIN_TRACKED_REQUESTS")
                   or os.environ.get("SAIL_TRACKED_REQUESTS", "500"))

# Password policy (configurable via env vars for production vs dev)
MIN_PASSWORD_LENGTH = _app_settings.min_password_length
REQUIRE_UPPERCASE = _app_settings.require_uppercase
REQUIRE_LOWERCASE = _app_settings.require_lowercase
REQUIRE_DIGIT = _app_settings.require_digit
REQUIRE_SPECIAL = _app_settings.require_special


def _kdf_input(password: str) -> bytes:
    """Pre-hash passwords so bcrypt never truncates long UTF-8 input."""
    return hashlib.sha256(password.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    """Hash a password with bcrypt cost 12."""
    return bcrypt.hashpw(_kdf_input(password), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a stored hash."""
    if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bool(
                bcrypt.checkpw(_kdf_input(plain_password), hashed_password.encode())
            )
        except Exception:
            return False
    if "$" not in hashed_password:
        return False
    salt, stored_hash = hashed_password.split("$", 1)
    # Recompute hash with the same salt
    computed = hashlib.sha512((salt + plain_password).encode()).hexdigest()
    for _ in range(1000):
        computed = hashlib.sha512((salt + computed).encode()).hexdigest()
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(computed, stored_hash)


def is_legacy_password_hash(hashed_password: str) -> bool:
    """Return whether a stored password uses the legacy SHA-512 format."""
    return not hashed_password.startswith(("$2a$", "$2b$", "$2y$"))


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token (PyJWT, HS256 allow-list)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        return None


# ---------------------------------------------------------------------------
# Brute force protection
# ---------------------------------------------------------------------------

def record_failed_login(username: str) -> int:
    """Record a failed login attempt. Returns current attempt count."""
    now = datetime.now(UTC)
    if username not in _login_attempts:
        _login_attempts[username] = []
    
    _login_attempts[username].append(now.timestamp())
    
    # Keep bounded
    while len(_login_attempts) > _max_tracked:
        oldest = min(_login_attempts.items(), key=lambda x: x[1][0])
        del _login_attempts[oldest[0]]
    
    return len(_login_attempts[username])


def is_login_locked(username: str) -> tuple[bool, float]:
    """Check if login is locked. Returns (locked, remaining_lockout_seconds)."""
    now = datetime.now(UTC)
    if username not in _login_attempts:
        return False, 0
    
    cutoff = now.timestamp() - LOGIN_LOCKOUT_MINUTES * 60
    recent_failures = [t for t in _login_attempts[username] if t > cutoff]
    _login_attempts[username] = recent_failures
    
    if len(recent_failures) >= LOGIN_MAX_ATTEMPTS:
        # Calculate remaining lockout
        oldest = recent_failures[0]
        remaining = int((oldest + LOGIN_LOCKOUT_MINUTES * 60) - now.timestamp())
        return True, max(0, remaining)
    
    return False, 0


def clear_failed_logins(username: str) -> None:
    """Clear failed login attempts on successful login."""
    _login_attempts.pop(username, None)


# ---------------------------------------------------------------------------
# Password policy validation
# ---------------------------------------------------------------------------

def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets security requirements.
    
    Returns (is_valid, error_message).
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    
    if REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if REQUIRE_LOWERCASE and not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if REQUIRE_DIGIT and not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    if REQUIRE_SPECIAL and not any(not c.isalnum() for c in password):
        return False, "Password must contain at least one special character"
    
    return True, ""


# ---------------------------------------------------------------------------
# Authentication middleware
# ---------------------------------------------------------------------------

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Extract current user from JWT token in Authorization header."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    username = payload.get("sub")
    if username is None:
        raise credentials_exception
    return {"username": username, "token": token}


def _get_user_by_username(username: str) -> dict | None:
    """Look up a user by username from the database, returning a minimal dict."""
    try:
        from backend.models.use_case import User
        settings = __import__("backend.config", fromlist=["get_settings"]).get_settings()
        engine = create_engine(settings.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            user = session.query(User).filter(User.username == username).first()
            if user and user.is_active:
                return {
                    "username": user.username,
                    "email": user.email,
                    "display_name": user.display_name,
                    "department": user.department,
                    "is_admin": user.is_admin,
                    "role": user.role,
                    "sales_role": getattr(user, "sales_role", None),
                    "user_id": user.id
                }
        finally:
            session.close()
    except Exception:
        pass  # DB lookup failure is non-fatal — fall back to anonymous
    return None


def get_user_from_request(request: Request) -> dict | None:
    """Extract user from Request header for optional authentication.

    Returns a dict with keys: username, email, display_name, department.
    Falls back to None if no Bearer token is present or if the token is invalid
    or the user cannot be found in the database.
    """
    auth_header = request.headers.get("Authorization", "")
    api_key = request.headers.get("X-API-Key", "")

    # Check for API key header first (for key-based auth)
    if api_key and os.environ.get("SAIL_DEPT_RESTRICTIONS", ""):
        try:
            restrictions = get_api_key_dept_restrictions(api_key)
            if restrictions is not None:
                # API key has restrictions configured
                allowed = list(restrictions["all_customers"]) if restrictions["all_customers"] else []
                if restrictions["is_admin"]:
                    allowed.append("all")
                return {
                    # Safe label, never the raw key (the raw key would leak
                    # into created_by / audit display fields — operator
                    # ruling R3, Part 13 DV wave 2026-10-30).
                    "username": "dept-api-key",
                    "department": None,
                    "allowed_departments": allowed,
                    "customer_allowed_departments": restrictions["customers"],
                    "is_admin": 1 if restrictions["is_admin"] else 0,
                }
        except Exception:
            pass  # Invalid API key, continue with JWT

    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]  # Remove "Bearer " prefix
    payload = decode_access_token(token)
    if payload is None:
        return None
    username = payload.get("sub")
    if username is None:
        return None
    # Look up full user record from DB so the service layer has department context
    user = _get_user_by_username(username)
    if user is not None:
        # Add junction table customer access context
        user["customer_ids"] = []
        user["junction_roles"] = {}
        try:
            from backend.models.use_case import CustomerUser
            settings = __import__("backend.config", fromlist=["get_settings"]).get_settings()
            db_session = sessionmaker(bind=create_engine(settings.database_url))()
            try:
                cu_records = (
                    db_session.query(CustomerUser)
                    .filter(CustomerUser.user_id == user.get("user_id"))
                    .all()
                )
                for cu in cu_records:
                    user["customer_ids"].append(cu.customer_id)
                    user["junction_roles"][cu.customer_id] = cu.role
                # RBAC memberships (one query): membership_roles + section_grants
                from backend.services.sales_access import load_membership_context
                load_membership_context(user, db_session)
            finally:
                # Closing here (not at GC time) is load-bearing: the session
                # holds a connection with an open transaction; an open
                # transaction on a shared pooled connection (StaticPool in
                # tests) can be rolled back later by this session's teardown,
                # destroying another session's uncommitted work on the same
                # connection.
                db_session.close()
        except Exception:
            pass  # Junction lookup failure is non-fatal
        return user
    # DB lookup failed (user not active, DB unavailable, etc.) —
    # fall back to JWT payload for audit trail so created_by/updated_by
    # record the real username instead of "anonymous"
    return {"username": username}


# ---------------------------------------------------------------------------
# Department restrictions
# ---------------------------------------------------------------------------

_DEPT_RESTRICTIONS_RAW = os.environ.get("SAIL_DEPT_RESTRICTIONS", "")


def _parse_dept_restrictions() -> dict:
    """Parse department restrictions from env var into a lookup dict.
    
    Returns: {api_key: {"customers": {cust_name: [dept1, ...], ...}, "all_customers": [dept1, ...], "is_admin": bool}}
    """
    if not _DEPT_RESTRICTIONS_RAW.strip():
        return {}

    result = {}
    for key_block in _DEPT_RESTRICTIONS_RAW.split(","):
        key_block = key_block.strip()
        if not key_block or ":" not in key_block:
            continue
        
        # Split into key and scope: parts
        # Format: key:scope:dept1|dept2
        parts = key_block.split(":", 2)
        if len(parts) < 3:
            continue
        
        api_key = parts[0]
        scope = parts[1]  # "all" or a customer name
        dept_string = parts[2]
        departments = [d.strip() for d in dept_string.split("|") if d.strip()]
        
        if api_key not in result:
            result[api_key] = {"customers": {}, "all_customers": [], "is_admin": False}
        
        if scope == "all":
            result[api_key]["all_customers"].extend(departments)
            result[api_key]["is_admin"] = True
        else:
            if scope not in result[api_key]["customers"]:
                result[api_key]["customers"][scope] = []
            result[api_key]["customers"][scope].extend(departments)
    
    return result


_DEPT_RESTRICTIONS = _parse_dept_restrictions()


def get_api_key_dept_restrictions(api_key: str) -> dict | None:
    """Get department restrictions for a specific API key."""
    return _DEPT_RESTRICTIONS.get(api_key)


def _user_has_dept_access(
    user: dict | None,
    department: str | None,
    customer_name: str | None = None,
) -> bool:
    """Check if user has permission to access a department (optionally customer-scoped).
    
    Returns True if:
    - No restrictions configured (open access)
    - User has 'all' access (admin)
    - Department is in user's allowed list
    - Customer is in user's allowed scope (for customer-scoped restrictions)
    - User is anonymous (auth disabled)
    """
    if user is None or department is None:
        return True
    
    allowed = user.get("allowed_departments")
    if allowed is None:
        return True  # No restrictions configured
    
    if "all" in allowed:
        return True
    
    # Direct department match
    if department in allowed:
        return True
    
    # If customer-scoped restrictions are configured, check customer context
    if customer_name:
        customer_deps = user.get("customer_allowed_departments", {}).get(customer_name, [])
        if department in customer_deps:
            return True
    
    return False
