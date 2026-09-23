from typing import Dict, List

import openai

from application.ports.ai.ai_port import AIService
from config.config import AIModelConfig


class YandexAIMainModelService(AIService):
    def __init__(self, config: AIModelConfig):
        self.client = openai.OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            project=config.cloud_folder
        )
        self.ai_model = config.model
        self.ai_temperature = config.temperature
        self.ai_max_tokens = config.max_tokens
        self.instructions = config.instruction

    async def get_ai_response_with_context(self, 
        user_message: str,
        context: List[Dict[str, str]]
        ) -> str:

        context_str = ""
        for msg in context:
            context_str += f"{msg['role']}: {msg['content']}\n"
        
        full_input = context_str + f"user: {user_message}"

        response = self.client.responses.create(
            model=self.ai_model,
            temperature=self.ai_temperature,
            max_output_tokens=self.ai_max_tokens,
            input=full_input,
            instructions=self.instructions
        )
        return response.output_text
    
    async def get_simple_response(self, user_message: str) -> str:
        response = self.client.responses.create(
            model=self.ai_model,
            temperature=self.ai_temperature,
            max_output_tokens=self.ai_max_tokens,
            input=user_message,
            instructions=self.instructions
        )
        return response.output_text
    
    async def generate_task(self, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.ai_model,
            temperature=self.ai_temperature,
            max_output_tokens=self.ai_max_tokens,
            instructions=self.instructions,
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text