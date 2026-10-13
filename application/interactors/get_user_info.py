from datetime import datetime
from pydantic import BaseModel
from application.repositories.user_repository import UserRepository
from domain.entities.user import User

class UserProfileResponse(BaseModel):
    id: int
    username: str
    first_name: str
    middle_name: str
    last_name: str
    group: str
    role: str
    current_streak: int
    longest_streak: int

class GetUserProfile:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def execute(self, user_id: int) -> UserProfileResponse:
        user: User = await self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        group_name = ""
        if user.group:
            spec_name = user.group.specialty.short_name if user.group.specialty else ""
            group_name = f"{user.group.year}{spec_name}{user.group.group_number}"

        role_value = user.role.value if hasattr(user.role, 'value') else user.role

        return UserProfileResponse(
            id=user.id,
            username=user.username,
            first_name=user.first_name or "",
            middle_name=user.middle_name or "",
            last_name=user.last_name or "",
            group=group_name,
            role=role_value,
            current_streak=user.current_streak,
            longest_streak=user.longest_streak,
        )

    