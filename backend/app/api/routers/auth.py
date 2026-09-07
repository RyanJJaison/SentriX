from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.users_store import get_user
from app.models.schemas import Token, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Token:
    user = get_user(form_data.username)
    if user is None or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={"sub": user["username"], "role": user["role"], "agency": user["agency"]}
    )
    return Token(access_token=token)


@router.get("/me", response_model=UserPublic)
def read_current_user(user: UserPublic = Depends(get_current_user)) -> UserPublic:
    return user
