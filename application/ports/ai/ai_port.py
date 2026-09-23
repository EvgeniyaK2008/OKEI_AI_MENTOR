from abc import ABC, abstractmethod
from typing import Dict, List


class AIService(ABC):
    @abstractmethod
    async def get_ai_response_with_context(
        self, 
        user_message: str,
        context: List[Dict[str, str]],
        **kwargs 
    ) -> str:
        pass

    @abstractmethod
    async def get_simple_response(self, user_message: str) -> str:
        pass

    @abstractmethod
    async def generate_task(self, prompt: str):
        pass
