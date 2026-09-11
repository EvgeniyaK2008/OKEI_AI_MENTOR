import re
from typing import List

from fastapi import logger

from application.services.dialog_service import DialogService
from application.repositories.dialog_repository import DialogRepository
from application.ports.ai.ai_port import AIService
from application.repositories.skill_matrix_repository import SkillMatrixRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.user_repository import UserRepository
from application.repositories.specialty_repository import SpecialtyRepository
from application.use_cases.get_skill_for_student import GetSkillForStudent

from domain.entities.session import Session
from domain.entities.skill_matrix import SkillMatrix
from domain.entities.student_progress import StudentProgress
from domain.entities.user import User, UserRole
from domain.entities.study import Specialty, Department, Groups
from domain.entities.dialog import Dialog

import uuid
from datetime import datetime

from domain.entities.dialog import Dialog


class AIContextService:
    def __init__(
            self, 
            dialog_service: DialogService,
            dialog_repository: DialogRepository,
            ai_service: AIService,
            matrix_repository: SkillMatrixRepository,
            student_progress_repository: StudentProgressRepository,
            user_repository: UserRepository,
            speciality_repository: SpecialtyRepository,
            instruction: str,
            get_skill_for_student: GetSkillForStudent
            ):
        self.dialog_service = dialog_service
        self.dialog_repository = dialog_repository
        self.ai_service = ai_service
        self.instruction = instruction
        self.student_progress_repository = student_progress_repository
        self.matrix_repository = matrix_repository
        self.user_repository = user_repository
        self.speciality_repository = speciality_repository
        self.get_skill_for_student = get_skill_for_student

    async def get_response_with_history(self, user_id: int, user_message: str):
        dialogs = await self.dialog_service.get_user_history(user_id, limit=10)

        dialog_history = []
        for dialog in dialogs:
            dialog_history.extend(dialog.to_context_messages())

        return await self.ai_service.get_ai_response_with_context(
            user_id=user_id,
            user_message=user_message,
            context=dialog_history
        )

    async def start_skill_session(self, user_id: int) -> str:
        prompt = await self.form_question_instruction(user_id)
        question = await self.ai_service.generate_task(prompt)
        question_id = str(uuid.uuid4())

        await self.dialog_service.save(
            user_id=user_id,
            user_message="",
            ai_response=question,
            question_id=question_id,
            user_message_time=None,
            ai_response_time=datetime.now()
            )

        return question, prompt, question_id

    async def evaluate_answer(
        self, 
        question_id: int, 
        user_id: int, 
        user_message_time: datetime = None,
        ):

        question_history: List[Dialog] = await self.dialog_service.get_user_history(user_id=user_id, limit=500, question_id=question_id)

        result = await self.get_student_result(question_history=question_history)

        student_progress = StudentProgress(
            student_id=user_id,
            skill_id=result['skill'],
            level=result['level'],
            weaknesses=result['weaknesses']
        )

        await self.student_progress_repository.upsert(progress=student_progress)
        
    async def form_question_instruction(self, user_id: int) -> str:        
        user: User = await self.user_repository.find_by_id(user_id)
        if (datetime.now().year - user.group.year) == 0:
            course = 1
        else:
            course: int = datetime.now().year - user.group.year 

        matrix: SkillMatrix = await self.get_skill_for_student.execute(user_id)
        matrix_skill: str = matrix.skill 
        matrix_criterion: str = matrix.criterions
        student_progress: StudentProgress | None = await self.student_progress_repository.find_by_student_and_skill(student_id=user_id, skill_id=matrix.id)
        student_progress_level: int = 0
        weaknesses: str = ""
        if student_progress is not None:
            student_progress_level = student_progress.level
            weaknesses = student_progress.weaknesses
        speciality: Specialty = await self.speciality_repository.find_by_id(matrix.specialty_id)

        question_instruction = f"""
        Сделай задание для отработки навыка {matrix_skill} для студента специальности {speciality.full_name} {course} курса.

        Данные о студенте:
        - Прогресс по навыку: {student_progress_level}%
        - Проблемные места: {weaknesses if weaknesses else 'не выявлены'}

        Критерии освоения навыка:
        {matrix_criterion}

        Требования:
        1. Задание должно быть практикоориентированным если это практический навык и открытый вопрос если теория
        2. Уровень сложности должен соответствовать {course} курсу
        3. В конце напиши критерии, по которым будет оцениваться решение

        Обязательно напиши текст задания.
        """

        return question_instruction 

    def _parse_ai_result(self, ai_response: str):
        ai_response = ai_response.strip()
        match = re.search(r'^(\d{1,3})', ai_response)
        if not match:
            logger.warning(f"Failed to parse percentage from: {ai_response}")
            return None, ai_response
        percentage = int(match.group(1))
        weaknesses = ai_response[match.end():].strip()
        weaknesses = re.sub(r'^[%\s-]+', '', weaknesses)
        return percentage, weaknesses

    async def get_student_result(self, question_history: List[Dialog]) -> dict:
        dialog = question_history[-5:]
        dialog: Dialog = await self.dialog_repository.find_by_id(dialog.id)
        user_id: int = dialog.user_id

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
        
        level, weaknesses = self._parse_ai_result(ai_answer)

        result = {
            'level': level,
            'weaknesses': weaknesses,
            'skill': skill_id
        }

        return result

