from application.ports.ai.ai_port import AIService
from application.repositories.dialog_repository import DialogRepository
from domain.entities.dialog import Dialog


prompt = 'Определи где ответ студента на вопрос '

class DetectStudentsAnswer:
    def __init__(
        self, 
        ai_service: AIService,
        dialog_repo: DialogRepository
    ):
        self.ai_service = ai_service
        self.dialog_repo = dialog_repo

    async def execute(self, question_id: int) -> str | bool:
        # get the last question_id and the first appearing in the dialog to pass into the model
        # then pass the dialog to the model
        # ask to get the exact message with answer
        # * it will be called every message with question id and detect

        question_history: list[Dialog] = await self.dialog_repo.get_dialogs_by_question(question_id=question_id)
        question: str = question_history[0].ai_response
        prompt = f"Определи где ответ студента на вопрос {question} и выведи мне одно сообщение с ответом студента. Если ответа нет верни сообщение 'False'"
        
        