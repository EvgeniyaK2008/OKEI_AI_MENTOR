from abc import ABC, abstractmethod


class StatsRepository(ABC):

    @abstractmethod
    async def get_total_students(self) -> int:
        pass

    @abstractmethod
    async def get_active_groups_count(self) -> int:
        pass

    @abstractmethod
    async def get_avg_progress_by_skill(self) -> list[dict]:
        pass

    @abstractmethod
    async def get_weakest_skills(self, limit: int) -> list[dict]:
        pass

    @abstractmethod
    async def get_activity_by_group(self) -> list[dict]:
        pass

    @abstractmethod
    async def get_completed_tasks_by_group(self) -> list[dict]:
        pass

    @abstractmethod
    async def get_daily_activity(self, days: int) -> list[dict]:
        pass