"""FastAPI cloud service skeleton: registration, API key auth, usage/rate limiting.

Epic 8.1's scope only — the memory endpoints themselves (Epic 8.2's cloud
`GraphStoreBase` backend) aren't wired in here yet; this is the
auth/quota shell they'll sit behind.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .auth import AuthenticatedUser, AuthStore


class RegisterRequest(BaseModel):
    email: str


class RegisterResponse(BaseModel):
    user_id: str
    api_key: str  # shown once, at registration


def create_app(auth_store: AuthStore | None = None, rate_limit_per_key: int = 1000) -> FastAPI:
    store = auth_store or AuthStore()
    app = FastAPI(title="memory-core cloud API")

    def require_api_key(x_api_key: str = Header(...)) -> AuthenticatedUser:
        user = store.authenticate(x_api_key)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid or revoked API key")
        return user

    def enforce_quota(user: AuthenticatedUser = Depends(require_api_key)) -> AuthenticatedUser:  # noqa: B008
        if store.usage_count(user.api_key_id) >= rate_limit_per_key:
            raise HTTPException(status_code=429, detail="API key quota exceeded")
        return user

    @app.post("/users/register", response_model=RegisterResponse)
    def register(req: RegisterRequest) -> RegisterResponse:
        issued = store.register_user(req.email)
        return RegisterResponse(user_id=issued.user_id, api_key=issued.raw_key)

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(enforce_quota)) -> dict[str, str]:  # noqa: B008
        store.record_usage(user.api_key_id, endpoint="/me")
        return {"user_id": user.user_id}

    app.state.auth_store = store
    return app


app = create_app()
