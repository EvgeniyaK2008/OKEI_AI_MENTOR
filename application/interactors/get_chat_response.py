'''
get_response_with_history
GetChatResponse
application/use_cases/get_chat_response.py
'''
from dataclasses import dataclass

from domain.entities.dialog import Dialog

from application.services.dialog_service import DialogService 
from application.ports.ai.ai_port import AIService

@dataclass
class UserMessage:
    user_id: int
    message: str

@dataclass
class GetChatResponseWithContextResponse:
    response: str


class GetChatResponseWithContext:
    async def execute(
        self,
        user_message: UserMessage,
        dialog_service: DialogService,
        ai_service: AIService
        ) -> str:
        
        user_id, message = user_message.user_id, user_message.message

        dialogs = await dialog_service.get_user_history(user_id=user_id, limit=10)

        dialog_history = []
        for dialog in dialogs:
            dialog_history.extend(dialog.to_context_messages())

        response = await ai_service.get_ai_response_with_context(
            user_message=message,
            context=dialog_history
        )

        return GetChatResponseWithContextResponse(response=response)
