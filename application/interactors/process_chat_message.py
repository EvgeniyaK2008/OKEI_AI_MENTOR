from datetime import datetime
from pydantic import BaseModel
from application.services.dialog_service import DialogService
from application.ports.ai.ai_port import AIService
from application.interactors.detect_student_answer import DetectStudentsAnswer, DetectStudentsAnswerResponse
from application.interactors.evaluate_student_answer import EvaluateStudentAnswer, EvaluateStudentAnswerResponse

class ChatRequestData(BaseModel):
    message: str
    question_id: str | None

class ChatResponseData(BaseModel):
    message: str
    question_id: str | None
    assessment: EvaluateStudentAnswerResponse | None
    task_completed: bool

class ProcessChatMessage:
    def __init__(
        self,
        dialog_service: DialogService,
        ai_service: AIService,
        detect_case: DetectStudentsAnswer,
        evaluate_case: EvaluateStudentAnswer
    ):
        self.dialog_service = dialog_service
        self.ai_service = ai_service
        self.detect_case = detect_case
        self.evaluate_case = evaluate_case

    async def execute(self, user_id: int, data: ChatRequestData) -> ChatResponseData:
        assessment = None
        
        if data.question_id:
            detection_result: DetectStudentsAnswerResponse = await self.detect_case.execute(data.question_id)
            if detection_result.answer_found:
                assessment = await self.evaluate_case.execute(data.question_id)

        ai_response_text = await self.ai_service.get_ai_response_with_context(
            user_id=user_id, 
            user_message=data.message,
            context_assessment=assessment
        )

        user_message_time = datetime.now()
        ai_response_time = datetime.now()
        
        await self.dialog_service.save(
            user_id=user_id,
            user_message=data.message,
            ai_response=ai_response_text,
            question_id=data.question_id,
            user_message_time=user_message_time,
            ai_response_time=ai_response_time,
        )

        return ChatResponseData(
            message=ai_response_text,
            question_id=data.question_id,
            assessment=assessment,
            task_completed=assessment is not None
        )