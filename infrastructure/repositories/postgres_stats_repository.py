from datetime import datetime, timedelta

from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from application.repositories.stats_repository import StatsRepository
from infrastructure.database.models import (
    UserModel,
    GroupModel,
    SpecialtyModel,
    SkillMatrixModel,
    StudentProgressModel,
    DialogModel,
)


class AsyncPostgresStatsRepository(StatsRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_total_students(self) -> int:
        result = await self.session.execute(
            select(func.count(UserModel.id)).where(UserModel.role == "student")
        )
        return result.scalar() or 0

    async def get_active_groups_count(self) -> int:
        result = await self.session.execute(
            select(func.count(GroupModel.id)).where(GroupModel.is_active == True)
        )
        return result.scalar() or 0

    async def get_avg_progress_by_skill(self) -> list[dict]:
        result = await self.session.execute(
            select(
                SkillMatrixModel.id,
                SkillMatrixModel.skill,
                func.avg(StudentProgressModel.level).label("avg_level"),
                func.count(StudentProgressModel.student_id).label("students_count"),
            )
            .join(StudentProgressModel, StudentProgressModel.skill_id == SkillMatrixModel.id)
            .group_by(SkillMatrixModel.id, SkillMatrixModel.skill)
            .order_by(func.avg(StudentProgressModel.level).desc())
        )
        rows = result.all()
        return [
            {
                "skill_id": row.id,
                "skill": row.skill,
                "avg_level": round(float(row.avg_level), 1),
                "students_count": row.students_count,
            }
            for row in rows
        ]

    async def get_weakest_skills(self, limit: int) -> list[dict]:
        result = await self.session.execute(
            select(
                SkillMatrixModel.id,
                SkillMatrixModel.skill,
                func.avg(StudentProgressModel.level).label("avg_level"),
                func.count(StudentProgressModel.student_id).label("students_count"),
            )
            .join(StudentProgressModel, StudentProgressModel.skill_id == SkillMatrixModel.id)
            .group_by(SkillMatrixModel.id, SkillMatrixModel.skill)
            .order_by(func.avg(StudentProgressModel.level).asc())
            .limit(limit)
        )
        rows = result.all()
        return [
            {
                "skill_id": row.id,
                "skill": row.skill,
                "avg_level": round(float(row.avg_level), 1),
                "students_count": row.students_count,
            }
            for row in rows
        ]

    async def get_activity_by_group(self) -> list[dict]:
        result = await self.session.execute(
            select(
                GroupModel.id,
                SpecialtyModel.short_name,
                GroupModel.group_number,
                GroupModel.year,
                func.count(DialogModel.id).label("total_messages"),
                func.count(func.distinct(DialogModel.question_id)).label("total_tasks"),
            )
            .join(UserModel, UserModel.group_id == GroupModel.id)
            .join(DialogModel, DialogModel.user_id == UserModel.id)
            .join(SpecialtyModel, SpecialtyModel.id == GroupModel.specialty_id)
            .where(GroupModel.is_active == True)
            .group_by(GroupModel.id, SpecialtyModel.short_name, GroupModel.group_number, GroupModel.year)
            .order_by(func.count(DialogModel.id).desc())
        )
        rows = result.all()
        return [
            {
                "group_id": row.id,
                "group_name": f"{datetime.now().year - row.year + 1}{row.short_name}{row.group_number}",
                "total_messages": row.total_messages,
                "total_tasks": row.total_tasks,
            }
            for row in rows
        ]

    async def get_completed_tasks_by_group(self) -> list[dict]:
        result = await self.session.execute(
            select(
                GroupModel.id,
                SpecialtyModel.short_name,
                GroupModel.group_number,
                GroupModel.year,
                func.count(func.distinct(DialogModel.question_id)).label("completed_tasks"),
                func.count(func.distinct(DialogModel.user_id)).label("active_students"),
            )
            .join(UserModel, UserModel.group_id == GroupModel.id)
            .join(DialogModel, DialogModel.user_id == UserModel.id)
            .join(SpecialtyModel, SpecialtyModel.id == GroupModel.specialty_id)
            .where(DialogModel.question_id.isnot(None))
            .where(GroupModel.is_active == True)
            .group_by(GroupModel.id, SpecialtyModel.short_name, GroupModel.group_number, GroupModel.year)
            .order_by(func.count(func.distinct(DialogModel.question_id)).desc())
        )
        rows = result.all()
        return [
            {
                "group_id": row.id,
                "group_name": f"{datetime.now().year - row.year + 1}{row.short_name}{row.group_number}",
                "completed_tasks": row.completed_tasks,
                "active_students": row.active_students,
            }
            for row in rows
        ]

    async def get_daily_activity(self, days: int) -> list[dict]:
        since = datetime.now() - timedelta(days=days)
        result = await self.session.execute(
            select(
                cast(DialogModel.user_message_time, Date).label("day"),
                GroupModel.id.label("group_id"),
                SpecialtyModel.short_name,
                GroupModel.group_number,
                GroupModel.year,
                func.count(DialogModel.id).label("messages_count"),
            )
            .join(UserModel, UserModel.id == DialogModel.user_id)
            .join(GroupModel, GroupModel.id == UserModel.group_id)
            .join(SpecialtyModel, SpecialtyModel.id == GroupModel.specialty_id)
            .where(DialogModel.user_message_time >= since)
            .where(GroupModel.is_active == True)
            .group_by(
                cast(DialogModel.user_message_time, Date),
                GroupModel.id,
                SpecialtyModel.short_name,
                GroupModel.group_number,
                GroupModel.year,
            )
            .order_by(cast(DialogModel.user_message_time, Date).desc())
        )
        rows = result.all()
        return [
            {
                "day": str(row.day),
                "group_id": row.group_id,
                "group_name": f"{datetime.now().year - row.year + 1}{row.short_name}{row.group_number}",
                "messages_count": row.messages_count,
            }
            for row in rows
        ]