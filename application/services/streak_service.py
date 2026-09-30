from datetime import date, timedelta

from application.repositories.user_repository import UserRepository
from domain.entities.user import User


class StreakService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def update(self, user_id: int) -> User:
        user: User = await self.user_repo.find_by_id(user_id)
        today: date = date.today()

        if user.last_activity_date == today:
            return user

        yesterday: date = today - timedelta(days=1)

        if user.last_activity_date == yesterday:
            user.current_streak += 1
        else:
            user.current_streak = 1

        if user.current_streak > user.longest_streak:
            user.longest_streak = user.current_streak

        await self.user_repo.update(user)   