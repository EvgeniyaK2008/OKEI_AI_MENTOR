from typing import List

from domain.entities.skill_matrix import SkillMatrix
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.skill_matrix_repository import SkillMatrixRepository
from application.repositories.user_repository import UserRepository
from domain.entities.student_progress import StudentProgress
from domain.entities.user import User



class GetSkillForStudent:
    def __init__(
        self,
        student_progress_repo: StudentProgressRepository,
        skill_matrix_repo: SkillMatrixRepository,
        user_repo: UserRepository):
        self.student_progress_repo = student_progress_repo
        self.skill_matrix_repo = skill_matrix_repo
        self.user_repo = user_repo

    async def execute(self, student_id: int) -> SkillMatrix:        
        user: User = await self.user_repo.find_by_id(student_id)
        specialty_id: int = user.get_specialty_id()

        student_skills = await self.skill_matrix_repo.find_skills_with_progress(specialty_id, user.id)

        not_mastered = [
            (skill, progress)
            for skill, progress in student_skills
            if progress < 100
        ]

        if not not_mastered:
            return None

        next_progress, _ = min(not_mastered, key=lambda p: p[0].learn_order)
        return await self.skill_matrix_repo.find_by_id(next_progress.id)
