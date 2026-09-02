'''
get_response_with_history
GetChatResponse
application/use_cases/get_chat_response.py
'''
from dataclasses import dataclass

from domain.entities.dialog import Dialog

from application.services.dialog_service import DialogService 

@dataclass
class UserMessage:
    user_id: int
    user_message: str


class GetChatResponse:
    async def execute(self, user_message: UserMessage) -> str:
        dialogs = await dialog_service.get_user_history(UserMessage.user_id, limit=10)


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