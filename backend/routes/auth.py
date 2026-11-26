"""User authentication routes."""


from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.auth import (
    clear_failed_logins,
    create_access_token,
    get_user_from_request,
    hash_password,
    is_legacy_password_hash,
    is_login_locked,
    record_failed_login,
    validate_password_strength,
)
from backend.dependencies import get_db
from backend.models.use_case import User
from backend.schemas.use_case import (
    LoginRequest,
    LoginResponse,
    UserCreate,
    UserCreateAdmin,
    UserPasswordReset,
    UserResponse,
    UserUpdate,
)
from backend.services.auth_provider import (
    AuthUnavailable,
    DirectoryIdentity,
    link_or_create_directory_user,
    resolve_auth_backend,
)
from backend.services.user_service import UserService

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/register/", response_model=UserResponse)
def register_user(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user. New registrations require admin approval before login."""
    # Local self-registration can be disabled by the admin (Application
    # Settings → directory auth area) — e.g. when the directory is the
    # intended onboarding path.
    from backend.services.ldap_settings import effective_ldap_settings

    if not effective_ldap_settings(db).local_register_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is disabled. Contact an administrator.",
        )
    # Validate password strength
    is_valid, error_msg = validate_password_strength(user_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    existing_user = UserService.find_existing(db, user_data.username, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists"
        )

    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        display_name=user_data.display_name,
        department=user_data.department,
        approved=0,  # Pending approval by admin
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.post("/login/", response_model=LoginResponse)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Login and get JWT token. User must be approved by an admin."""
    # Check if login is locked due to brute force protection
    is_locked, remaining_seconds = is_login_locked(login_data.username)
    if is_locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {remaining_seconds} seconds.",
            headers={"Retry-After": str(remaining_seconds)},
        )

    # Resolve the auth provider and authenticate (P0: always local; P1 adds
    # directory resolution per the §3.1 table — local rows keep the exact
    # pre-seam bcrypt path, unknown usernames route to the directory when it
    # is enabled+configured, else fail uniformly through the local path).
    # is_active / approved checks below are provider-agnostic and unchanged.
    try:
        backend = resolve_auth_backend(db, login_data.username)
        identity = backend.authenticate(db, login_data.username, login_data.password)
    except AuthUnavailable:
        # Directory outage/misconfiguration — the ONE non-401 login outcome
        # (§3.1): a fixed ops message, no account or config details.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthUnavailable.MESSAGE,
        )
    user = identity
    if isinstance(identity, DirectoryIdentity):
        # Verified directory identity → map onto the local User row
        # (idempotent link by external_id / JIT create). The directory is
        # the password authority: JIT rows store no local hash.
        from backend.services.ldap_settings import effective_ldap_settings

        ldap_settings = effective_ldap_settings(db)
        try:
            user = link_or_create_directory_user(
                db,
                identity,
                login_data.username,
                auto_approve=ldap_settings.auto_approve,
                default_role=ldap_settings.default_role,
            )
        except AuthUnavailable as exc:
            # e.g. local-account collision (local-first precedence, §3.1).
            record_failed_login(login_data.username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            ) from exc
    if user is None:
        # Record failed login attempt
        record_failed_login(login_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    # Both provider paths end in a local User row (the DirectoryIdentity
    # branch links or JIT-creates one above, else raised) — narrow the
    # union for the attribute reads below.
    if not isinstance(user, User):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )
    if user.approved == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending approval by an administrator"
        )

    # Clear failed attempts on successful login
    clear_failed_logins(login_data.username)
    if not isinstance(identity, DirectoryIdentity) and is_legacy_password_hash(
        user.hashed_password
    ):
        user.hashed_password = hash_password(login_data.password)
        db.commit()

    token = create_access_token(data={"sub": user.username, "is_admin": bool(user.is_admin)})
    return LoginResponse(
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        token=token,
        department=user.department,
        is_admin=bool(user.is_admin),
        role=user.role or "user",
        # user is a local User row here (every DirectoryIdentity path mapped
        # to one above and raised 401/503 otherwise).
        sales_role=user.sales_role,
    )


@router.get("/me/", response_model=UserResponse)
def get_me(request: Request, db: Session = Depends(get_db)):
    """Get current user profile from JWT token."""
    user_info = get_user_from_request(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = UserService.get_by_username(db, user_info["username"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict()


@router.get("/settings/public/")
def get_public_auth_settings(db: Session = Depends(get_db)):
    """Unauthenticated public auth settings (drives the Login page).

    NO secrets, NO per-account data: just the flags the login form needs —
    whether local registration is available, whether the corporate directory
    is active (enabled AND not kill-switched), and a fixed hint line.
    """
    from backend.schemas.auth import AuthPublicSettingsResponse
    from backend.services.ldap_settings import effective_ldap_settings

    eff = effective_ldap_settings(db)
    ldap_active = eff.enabled and not eff.login_disabled
    hint = (
        "You can sign in with your corporate directory (LDAP/AD) account."
        if ldap_active
        else ""
    )
    return AuthPublicSettingsResponse(
        local_register_enabled=eff.local_register_enabled,
        ldap_enabled=ldap_active,
        login_hint=hint,
    )


# ---------------------------------------------------------------------------
# Admin-only endpoints (require admin role in JWT)
# ---------------------------------------------------------------------------

def _require_admin(request: Request, db: Session) -> User:
    """Check that the logged-in user from JWT is an admin; raise 403 otherwise."""
    user_info = get_user_from_request(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = UserService.get_by_username(db, user_info["username"])
    if not user or not user.is_admin or not user.is_active:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


@router.post("/approve/{username}/", response_model=UserResponse)
def approve_user(username: str, request: Request, db: Session = Depends(get_db)):
    """Approve a pending user registration. Admin-only."""
    _require_admin(request, db)
    target = UserService.get_by_username(db, username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.approved:
        return target.to_dict()
    target.approved = 1
    db.commit()
    db.refresh(target)
    return target.to_dict()


@router.get("/users/pending/", response_model=list[UserResponse])
def list_pending_users(request: Request, db: Session = Depends(get_db)):
    """List all users awaiting approval. Admin-only."""
    _require_admin(request, db)
    pending = UserService.list_pending(db)
    return [u.to_dict() for u in pending]


@router.get("/users/all/", response_model=list[UserResponse])
def list_all_users(request: Request, db: Session = Depends(get_db)):
    """List all users (active, inactive, approved, pending). Admin-only."""
    _require_admin(request, db)
    users = UserService.list_all(db)
    return [u.to_dict() for u in users]


def _service_error(e: ValueError) -> HTTPException:
    """Map service business-rule errors to HTTP status codes."""
    if e.args and e.args[0] == "User not found":
        return HTTPException(status_code=404, detail="User not found")
    if e.args and e.args[0] == "Account is managed by the corporate directory":
        # Directory-managed row (auth_provider='ldap'): password fields are
        # owned by the directory (plan §4) — 400, not 500.
        return HTTPException(
            status_code=400, detail="Account is managed by the corporate directory"
        )
    return HTTPException(status_code=400, detail=str(e))


@router.post("/users/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: "UserCreateAdmin",
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new user. Global admin only (0.2.11).

    The operator's in-app path for adding people the seed import missed
    (real managers after the 2026-10-14 org correction, new PS/MS staff,
    etc.). Defaults to a pending, inactive account — approve it from the
    Pending tab (mirrors the seeded name-only owners). Declared BEFORE the
    /users/{user_id}/ routes so the literal path wins (AUTH-01 ordering).
    """
    admin = _require_admin(request, db)
    is_valid, error_msg = validate_password_strength(payload.password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    try:
        return UserService.create_user(
            db,
            admin_id=admin.id,
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
            email=payload.email,
            department=payload.department,
            role=payload.role,
            sales_role=payload.sales_role,
            approved=payload.approved,
            is_active=payload.is_active,
        )
    except ValueError as e:
        raise _service_error(e)


@router.put("/users/{user_id}/", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Edit a user's profile fields and/or global role. Admin-only.

    Setting role to "admin" grants admin status (is_admin=1); any other
    role revokes it. An admin cannot change their own role.
    """
    admin = _require_admin(request, db)
    if user_data.role is not None and user_data.role != "admin" and user_id != admin.id:
        # clearing is_admin must never leave the system without a global admin
        # (self role changes are rejected by the service: "own role")
        from backend.services.membership_service import block_global_admin_change
        if block_global_admin_change(db, user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot demote the last global admin",
            )
    try:
        update_kwargs = {
            "display_name": user_data.display_name,
            "email": user_data.email,
            "department": user_data.department,
            "role": user_data.role,
        }
        if "sales_role" in user_data.model_fields_set:
            update_kwargs["sales_role"] = user_data.sales_role
        return UserService.update_user(
            db, user_id, admin_id=admin.id, **update_kwargs
        )
    except ValueError as e:
        raise _service_error(e)


@router.post("/users/{user_id}/reset-password/")
def reset_user_password(
    user_id: int,
    payload: UserPasswordReset,
    request: Request,
    db: Session = Depends(get_db),
):
    """Admin-initiated password reset (strength policy enforced). Admin-only."""
    _require_admin(request, db)
    is_valid, error_msg = validate_password_strength(payload.new_password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    try:
        UserService.reset_password(db, user_id, payload.new_password)
    except ValueError as e:
        raise _service_error(e)
    return {"message": f"Password for user {user_id} has been reset"}


@router.post("/users/{user_id}/deactivate/", response_model=UserResponse)
def deactivate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Deactivate an account (login blocked until re-activated). Admin-only.

    An admin cannot deactivate their own account.
    """
    admin = _require_admin(request, db)
    try:
        return UserService.set_active(db, user_id, admin.id, active=False)
    except ValueError as e:
        raise _service_error(e)


@router.post("/users/{user_id}/activate/", response_model=UserResponse)
def activate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Re-activate a deactivated account. Admin-only."""
    admin = _require_admin(request, db)
    try:
        return UserService.set_active(db, user_id, admin.id, active=True)
    except ValueError as e:
        raise _service_error(e)


@router.delete("/users/{user_id}/")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a user and their customer-junction rows. Admin-only.

    An admin cannot delete their own account.
    """
    admin = _require_admin(request, db)
    try:
        UserService.delete_user(db, user_id, admin.id)
    except ValueError as e:
        raise _service_error(e)
    return {"message": f"User {user_id} deleted"}
