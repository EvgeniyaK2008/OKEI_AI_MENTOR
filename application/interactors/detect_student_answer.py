from dataclasses import dataclass

from application.ports.ai.ai_port import AIService
from application.repositories.dialog_repository import DialogRepository
from domain.entities.dialog import Dialog


@dataclass
class DetectStudentsAnswerResponse:
    answer_found: bool
    answer_message: str | None


class DetectStudentsAnswer:
    def __init__(
        self, 
        ai_service: AIService,
        dialog_repo: DialogRepository
    ):
        self.ai_service = ai_service
        self.dialog_repo = dialog_repo

    async def execute(self, question_id: str) -> DetectStudentsAnswerResponse:
        # get the last question_id and the first appearing in the dialog to pass into the model
        # then pass the dialog to the model
        # ask to get the exact message with answer
        # * it will be called every message with question id and detect

        question_history: list[Dialog] = await self.dialog_repo.get_dialogs_by_question(question_id=question_id)
        if not question_history:
            return DetectStudentsAnswerResponse(answer_found=False, answer_message=None)

        context = []
        for dialog in question_history:
            if dialog.user_message:
                context.append({"role": "user", "content": dialog.user_message})
            if dialog.ai_response:
                context.append({"role": "assistant", "content": dialog.ai_response})
        
        question: str = question_history[0].ai_response

        prompt = f"""Определи где ответ студента на вопрос: {question}
            История диалога:
            {context}

            Инструкции:
            - Если студент дал окончательный ответ на задание, верни ТОЛЬКО текст его ответа
            - Если ответа нет или студент ещё думает, верни СТРОГО слово NO_ANSWER"""

        print('='*50)
        print(prompt)
        
        response: str = await self.ai_service.get_ai_response_with_context(user_message=prompt, context=context)

        print('-'*50)
        if response.strip().upper() == 'NO_ANSWER':
            print(f'НЕТ ОТВЕТА - {response.strip().upper()}')
            return DetectStudentsAnswerResponse(answer_found=False, answer_message=None)
        print(f'ОТВЕТ - {response.strip()}')
        return DetectStudentsAnswerResponse(answer_found=True, answer_message=response.strip())

    