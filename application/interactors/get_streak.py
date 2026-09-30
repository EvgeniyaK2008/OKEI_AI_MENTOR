

from dataclasses import dataclass

from application.repositories.user_repository import UserRepository
from application.services.streak_service import StreakService
from domain.entities.user import User


@dataclass
class GetStreakResponse:
    user_id: int
    current_streak: int
    longest_streak: int
    last_activity_date: str | None 

class GetStreak:
    def __init__(
        self,
        user_repo: UserRepository):
        self.user_repo = user_repo

    async def execute(self, user_id: int) -> GetStreakResponse:
        user: User = await self.user_repo.find_by_id(user_id=user_id)
        current_streak: int = user.current_streak
        longest_streak: int = user.longest_streak
        last_activity_date: int = user.last_activity_date if user.last_activity_date else None 

        return GetStreakResponse(user_id, current_streak, longest_streak, last_activity_date)
