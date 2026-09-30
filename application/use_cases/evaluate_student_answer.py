from dataclasses import dataclass
import re

from application.ports.ai.ai_port import AIService
from application.repositories.dialog_repository import DialogRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.services.dialog_service import DialogService
from application.use_cases.get_skill_for_student import GetSkillForStudent
from domain.entities.dialog import Dialog
from domain.entities.skill_matrix import SkillMatrix
from domain.entities.student_progress import StudentProgress

import logging
logger = logging.getLogger(__name__)

@dataclass
class EvaluateStudentAnswerRespose:
    level: int


class EvaluateStudentAnswer:
    def __init__(
            self,
            dialog_service: DialogService,
            student_progress_repo: StudentProgressRepository,
            get_skill_for_student: GetSkillForStudent,
            dialog_repo: DialogRepository,
            ai_service: AIService
            ):
        self.dialog_service = dialog_service
        self.student_progress_repo = student_progress_repo
        self.get_skill_for_student = get_skill_for_student
        self.dialog_repo = dialog_repo
        self.ai_service = ai_service
        
    async def execute(self, question_id: int):
        question_history: list[Dialog] = await self.dialog_repo.get_dialogs_by_question(question_id=question_id)
        user_id: int = question_history[0].user_id
        result = await self._get_student_result(question_history=question_history)

        student_progress = StudentProgress(
            student_id=user_id,
            skill_id=result['skill'],
            level=result['level'],
            weaknesses=result['weaknesses']
        )

        await self.student_progress_repo.upsert(progress=student_progress)
        return EvaluateStudentAnswerRespose(result['level'])

    async def _parse_ai_result(self, ai_response: str):
        ai_response = ai_response.strip()
        match = re.search(r'^(\d{1,3})', ai_response)
        if not match:
            logger.warning(f"Failed to parse percentage from: {ai_response}")
            return None, ai_response
        percentage = int(match.group(1))
        weaknesses = ai_response[match.end():].strip()
        weaknesses = re.sub(r'^[%\s-]+', '', weaknesses)
        return percentage, weaknesses

    async def _get_student_result(self, question_history: list[Dialog]) -> dict:
        user_id: int = question_history[0].user_id

        matrix: SkillMatrix = await self.get_skill_for_student.execute(student_id=user_id)

        skill: str = matrix.skill
        skill_id: int = matrix.id
        criterions: str = matrix.criterions 
            
        result_instruction =  f"""Оцени усвоение темы студентом по стобалльной шкале. 
                                Тема {skill}
                                Процент освоения считай только по первому ответу студента.
                                Последующие сообщения используй для определения слабостей студента в теме.
                                Критерии усвоения: {criterions}

                                Формат ответа (строго соблюдай):
                                [Число от 1 до 100]%
                                - [Слабость 1]
                                - [Слабость 2]
                                - [Слабость 3]
                                (добавь столько пунктов, сколько необходимо)

                                Пример:
                                65%
                                - не понимает синтаксис функций в Python
                                - путает параметры и аргументы
                                - не использует return правильно"""

        history_text = ""
        for message in question_history:
            role = "user"
            content = message.user_message
            history_text += f"{role}: {content}\n"
            role = "assistant"
            content = message.ai_response
            history_text += f"{role}: {content}\n"

        content = result_instruction + "\n\n" + history_text

        ai_answer = await self.ai_service.get_simple_response(user_message=content)  

        level, weaknesses = await self._parse_ai_result(ai_answer)

        result = {
            'level': level,
            'weaknesses': weaknesses,
            'skill': skill_id
        }

        print('+' * 50)
        print(result['level'], result['weaknesses'])

        return result

