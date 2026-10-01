from fastapi import Request, HTTPException, Depends
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta
from config.config import Config

config = Config.load()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = config.key
ALGORITHM = "HS256"


def hash_password(password: str):
    print(password)
    hashed = pwd_context.hash(password)
    return hashed


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, role: str = "student"):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=30)
    to_encode.update({
        "exp": expire,
        "role": role
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        raise HTTPException(
            status_code=401,
            detail="Please login"
        )
    
    try:
        token = auth_header.split(" ")[1] 
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

    user_id = payload.get("user_id")
    username = payload.get("username")
    role = payload.get("role")

    return {
        "user_id": user_id, 
        "username": username,
        "role": role
    }


def require_role(required_role: str):

    def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") != required_role:
            raise HTTPException(
                status_code=403,
                detail=f"Доступ запрещен. Требуется роль: {required_role}"
            )
        return current_user
    return role_checker
