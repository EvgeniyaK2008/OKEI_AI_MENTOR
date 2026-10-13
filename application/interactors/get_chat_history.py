from pydantic import BaseModel
from datetime import datetime
from typing import Literal
from application.repositories.dialog_repository import DialogRepository

class MessageItem(BaseModel):
    id: str
    role: Literal["user", "ai"]
    content: str
    timestamp: datetime | None
    question_id: str | None

class ChatHistoryResponseData(BaseModel):
    user_id: int
    username: str
    messages: list[MessageItem]

class GetChatHistory:
    def __init__(self, dialog_repo: DialogRepository):
        self.dialog_repo = dialog_repo

    async def execute(self, user_id: int, username: str, limit: int) -> ChatHistoryResponseData:
        dialogs = await self.dialog_repo.get_user_history(user_id=user_id, limit=limit)
        
        messages = []
        for dialog in dialogs:
            if dialog.user_message:
                messages.append(MessageItem(
                    id=f"{dialog.id}_user",
                    role="user",
                    content=dialog.user_message,
                    timestamp=dialog.user_message_time,
                    question_id=dialog.question_id,
                ))
            if dialog.ai_response:
                messages.append(MessageItem(
                    id=f"{dialog.id}_ai",
                    role="ai",
                    content=dialog.ai_response,
                    timestamp=dialog.ai_response_time,
                    question_id=dialog.question_id
                ))
        
        messages.sort(key=lambda m: m.timestamp or datetime.min)

        return ChatHistoryResponseData(
            user_id=user_id,
            username=username,
            messages=messages
        )