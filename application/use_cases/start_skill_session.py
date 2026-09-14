'''
start_skill_session
StartSkillSession
application/use_cases/start_skill_session.py
'''
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from domain.entities.skill_matrix import SkillMatrix
from domain.entities.student_progress import StudentProgress
from domain.entities.study import Specialty
from domain.entities.user import User

from application.ports.ai.ai_port import AIService
from application.repositories.specialty_repository import SpecialtyRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.user_repository import UserRepository
from application.services.dialog_service import DialogService
from application.use_cases.get_skill_for_student import GetSkillForStudent
from application.utils.academic import current_course

logger = logging.getLogger(__name__)


@dataclass
class StartSkillSessionResponse:
    question: str
    question_id: str


class StartSkillSession:
    def __init__(
        self,
        ai_service: AIService,
        dialog_service: DialogService,
        user_repo: UserRepository,
        get_skill_for_student: GetSkillForStudent,
        student_progress_repo: StudentProgressRepository,
        specialty_repo: SpecialtyRepository,
    ):
        self.ai_service = ai_service
        self.dialog_service = dialog_service
        self.user_repo = user_repo
        self.get_skill_for_student = get_skill_for_student
        self.student_progress_repo = student_progress_repo
        self.specialty_repo = specialty_repo

    async def execute(self, user_id: int) -> StartSkillSessionResponse:
        prompt = await self._form_question_instruction(user_id)
        question = await self.ai_service.generate_task(prompt)
        question_id = str(uuid.uuid4())

        await self.dialog_service.save(
            user_id=user_id,
            user_message="",
            ai_response=question,
            question_id=question_id,
            user_message_time=None,
            ai_response_time=datetime.now(),
        )

        return StartSkillSessionResponse(question=question, question_id=question_id)

    async def _form_question_instruction(self, user_id: int) -> str:
        user: User = await self.user_repo.find_by_id(user_id)
        course = current_course(user.group.year)

        matrix: SkillMatrix = await self.get_skill_for_student.execute(user_id)
        progress: StudentProgress | None = (
            await self.student_progress_repo.find_by_student_and_skill(
                student_id=user_id, skill_id=matrix.id
            )
        )
        specialty: Specialty = await self.specialty_repo.find_by_id(matrix.specialty_id)

        level = progress.level if progress else 0
        weaknesses = progress.weaknesses if progress else "не выявлены"

        return f"""
        Сделай задание для отработки навыка {matrix.skill} для студента специальности {specialty.full_name} {course} курса.

        Данные о студенте:
        - Прогресс по навыку: {level}%
        - Проблемные места: {weaknesses}

        Критерии освоения навыка:
        {matrix.criterions}

        Требования:
        1. Задание должно быть практикоориентированным если это практический навык и открытый вопрос если теория
        2. Уровень сложности должен соответствовать {course} курсу
        3. В конце напиши критерии, по которым будет оцениваться решение

        Обязательно напиши текст задания.
        """
        