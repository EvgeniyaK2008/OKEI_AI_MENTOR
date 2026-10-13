from pydantic import BaseModel
from application.repositories.user_repository import UserRepository
from application.services.auth import verify_password, create_access_token
from application.interactors.get_user_info import GetUserProfile, UserProfileResponse

class LoginResponse(BaseModel):
    token: str
    user: UserProfileResponse

class AuthenticateUser:
    def __init__(self, user_repo: UserRepository, get_user_profile: GetUserProfile):
        self.user_repo = user_repo
        self.get_user_profile = get_user_profile

    async def execute(self, username: str, password: str) -> LoginResponse:
        user = await self.user_repo.find_by_username(username)
        if not user or not verify_password(password, user.hashed_password):
            raise ValueError("Invalid credentials")

        token = create_access_token(
            data={"username": user.username, "user_id": user.id},
            role=user.role.value if hasattr(user.role, 'value') else user.role
        )
        
        user_profile = await self.get_user_profile.execute(user.id)

        return LoginResponse(token=token, user=user_profile)