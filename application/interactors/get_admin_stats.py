from dataclasses import dataclass

from application.repositories.stats_repository import StatsRepository


@dataclass
class AdminStatsResponse:
    total_students: int
    active_groups_count: int
    avg_progress_by_skill: list[dict]
    weakest_skills: list[dict]
    activity_by_group: list[dict]
    completed_tasks_by_group: list[dict]
    daily_activity: list[dict]


class GetAdminStats:
    def __init__(self, stats_repo: StatsRepository):
        self.stats_repo = stats_repo

    async def execute(self, days: int = 30) -> AdminStatsResponse:
        total_students = await self.stats_repo.get_total_students()
        active_groups_count = await self.stats_repo.get_active_groups_count()
        avg_progress_by_skill = await self.stats_repo.get_avg_progress_by_skill()
        weakest_skills = await self.stats_repo.get_weakest_skills(limit=5)
        activity_by_group = await self.stats_repo.get_activity_by_group()
        completed_tasks_by_group = await self.stats_repo.get_completed_tasks_by_group()
        daily_activity = await self.stats_repo.get_daily_activity(days=days)

        return AdminStatsResponse(
            total_students=total_students,
            active_groups_count=active_groups_count,
            avg_progress_by_skill=avg_progress_by_skill,
            weakest_skills=weakest_skills,
            activity_by_group=activity_by_group,
            completed_tasks_by_group=completed_tasks_by_group,
            daily_activity=daily_activity,
        )