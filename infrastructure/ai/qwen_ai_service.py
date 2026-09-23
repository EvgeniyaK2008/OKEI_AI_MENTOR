from typing import Dict, List

import ollama
from ollama import chat
import openai

from application.ports.ai.ai_port import AIService
from config.config import AIModelConfig


class QwenAIService(AIService):
    def __init__(self, config: AIModelConfig):
        self.client = openai.OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            project=config.cloud_folder,
        )
        self.ai_model = config.model
        self.ai_temperature = config.temperature
        self.ai_max_tokens = config.max_tokens
        self.instructions = config.instruction

    async def get_ai_response_with_context(
        self,
        user_message: str,
        context: List[Dict[str, str]],
    ) -> str:
        context_str = ""
        for msg in context:
            context_str += f"{msg['role']}: {msg['content']}\n"

        full_input = context_str + f"user: {user_message}"

        response = chat(
            model="qwen:0.5b",
            messages=[{"role": "user", "content": full_input}],
        )
        return response.message.content

    async def get_simple_response(self, user_text: str) -> str:
        response = chat(
            model="qwen:0.5b",
            messages=[{"role": "user", "content": user_text}],
        )
        return response.message.content

    async def generate_task(self, prompt: str) -> str:
        response = chat(
            model="qwen:0.5b",
            messages=[
                {"role": "system", "content": self.instructions},
                {"role": "user", "content": prompt},
            ],
        )
        return f"{prompt}\n{response.message.content}"