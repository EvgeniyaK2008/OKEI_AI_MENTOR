#main.py
import logging
import sys
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import BasicAuth
from dotenv import load_dotenv

from application.repositories.session_repository import SessionRepository
from application.repositories.skill_matrix_repository import SkillMatrixRepository
from application.repositories.group_repository import GroupRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.user_repository import UserRepository
from application.repositories.specialty_repository import SpecialtyRepository
from config.config import Config
from datetime import datetime, timezone


from infrastructure.ai.yandex_ai_service import YandexAIService
from infrastructure.ai.qwen_ai_service import QwenAIService
from application.services.ai_service import AIContextService
from application.services.user_service import UserService
from application.services.dialog_service import DialogService

from domain.entities.session import Session
from domain.entities.skill_matrix import SkillMatrix
from domain.entities.student_progress import StudentProgress
from domain.entities.user import User, UserRole
from domain.entities.study import Specialty, Department, Groups
from domain.entities.dialog import Dialog

from fastapi import FastAPI, Request, Form, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from typing import Optional, Any, List

from infrastructure.database.connection import get_db
from infrastructure.repositories.postgres_user_repository import AsyncPostgresUserRepository
from infrastructure.repositories.postgres_skill_matrix_repository import AsyncPostgresSkillMatrixRepository
from infrastructure.repositories.postgres_student_progress_repository import AsyncPostgresStudentProgressRepository
from infrastructure.repositories.postgres_group_repository import AsyncPostgresGroupRepository
from infrastructure.repositories.postgres_dialog_repository import AsyncPostgresDialogRepository
from infrastructure.repositories.postgres_specialty_repository import AsyncPostgresSpecialtyRepository
from application.services.user_service import UserService
from application.services.auth import hash_password, verify_password, create_access_token, get_current_user
from application.use_cases.get_skill_for_student import GetSkillForStudent
from presentation.web.fastapi.models import *

from pydantic import BaseModel, Field


class ProgressItem(BaseModel):
    skill: str
    level: int


class GroupItem(BaseModel):
    id: int
    name: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    group_id: Optional[int] = None


class RegisterResponse(BaseModel):
    user_id: int
    username: str


class LoginUser(BaseModel):
    id: int
    username: str
    first_name: str
    middle_name: str
    last_name: str
    group: str


class LoginResponse(BaseModel):
    token: str
    user: LoginUser


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    message: str
    question_id: Optional[str] = None


class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime | None = None


class ChatHistoryResponse(BaseModel):
    user_id: int
    username: str
    messages: list[MessageItem]


# ---------- App ----------

load_dotenv()
config = Config.load()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

async def get_user_service(db: AsyncSession = Depends(get_db)):
    user_repo = AsyncPostgresUserRepository(db)
    skill_repo = AsyncPostgresSkillMatrixRepository(db)
    progress_repo = AsyncPostgresStudentProgressRepository(db)
    return UserService(user_repo, skill_repo, progress_repo)

async def get_group_repo(db: AsyncSession = Depends(get_db)):
    return AsyncPostgresGroupRepository(db)

async def get_dialog_service(db: AsyncSession = Depends(get_db)):
    return DialogService(AsyncPostgresDialogRepository(db))

async def get_user_repo(db: AsyncSession = Depends(get_db)):
    return AsyncPostgresUserRepository(db)

async def get_specialty_repo(db: AsyncSession = Depends(get_db)):
    return AsyncPostgresSpecialtyRepository(db)

async def get_student_progress_repo(db: AsyncSession = Depends(get_db)):
    return AsyncPostgresStudentProgressRepository(db)

async def get_matrix_repo(db: AsyncSession = Depends(get_db)):
    return AsyncPostgresSkillMatrixRepository(db)


async def get_ai_service(db: AsyncSession = Depends(get_db)):
    user_repo = AsyncPostgresUserRepository(db)
    skill_matrix_repo = AsyncPostgresSkillMatrixRepository(db)
    student_progress_repo = AsyncPostgresStudentProgressRepository(db)
    specialty_repo = AsyncPostgresSpecialtyRepository(db)
    dialog_repo = AsyncPostgresDialogRepository(db)
    
    get_skill_for_student = GetSkillForStudent(
        student_progress_repo=student_progress_repo,
        skill_matrix_repo=skill_matrix_repo,
        user_repo=user_repo
    )
    
    return AIContextService(
        dialog_service=DialogService(dialog_repo),
        dialog_repository=dialog_repo,
        ai_service=YandexAIService(config),
        matrix_repository=skill_matrix_repo,
        student_progress_repository=student_progress_repo,
        user_repository=user_repo,
        speciality_repository=specialty_repo,
        instruction=config.ai_instruction,
        get_skill_for_student=get_skill_for_student
    )


@app.get('/progress', response_model=list[ProgressItem])
async def get_progress(
    request: Request,
    student_progress_repo: StudentProgressRepository = Depends(get_student_progress_repo),
    matrix_repo: SkillMatrixRepository = Depends(get_matrix_repo)
):
    current_user = get_current_user(request)
    user_id = current_user["user_id"]

    student_progress: List[StudentProgress] = await student_progress_repo.find_by_student_id(user_id)

    result = []
    for el in student_progress:
        skill = await matrix_repo.find_by_id(el.skill_id)
        result.append(ProgressItem(skill=skill.skill, level=el.level))
    return result


@app.get("/groups", response_model=list[GroupItem])
async def get_groups(group_repo: AsyncPostgresGroupRepository = Depends(get_group_repo)):
    groups = await group_repo.find_active_groups()

    return [
        GroupItem(id=g.id, name=f"{datetime.now.year - g.year}")
        for g in groups
    ]


@app.post('/register', response_model=RegisterResponse)
async def register(
    data: RegisterRequest,
    service: UserService = Depends(get_user_service),
    user_repo: UserRepository = Depends(get_user_repo),
    group_repo: AsyncPostgresGroupRepository = Depends(get_group_repo)
):
    existing = await user_repo.find_by_username(data.username)

    if existing:
        return JSONResponse(
            status_code=400,
            content={'success': False, 'error': "Username already exists"}
        )
    
    group = None
    if data.group_id:
        group = await group_repo.find_by_id(int(data.group_id))

    hashed_password = hash_password(data.password)

    user = await service.get_or_create_user(
        username=data.username,
        hashed_password=hashed_password,
        first_name="test",
        middle_name="test",
        last_name="test",
        group=group
    )
    return RegisterResponse(user_id=user.id, username=user.username)


@app.post('/login', response_model=LoginResponse)
async def login_page(
    data: LoginRequest, 
    user_service: UserService = Depends(get_user_service),
    user_repo: UserRepository = Depends(get_user_repo),
    group_repo: GroupRepository = Depends(get_group_repo),
    speciality_repo: SpecialtyRepository = Depends(get_specialty_repo)
    ):

    user = await user_repo.find_by_username(data.username)

    if not user or not verify_password(data.password, user.hashed_password):
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Invalid credentials"}
        )

    token = create_access_token({"username": user.username, "user_id": user.id})
    group = await group_repo.find_by_id(user.group.id)
    specialty = await speciality_repo.find_by_id(group.specialty.id)
    group_name = str(group.year) + str(specialty.short_name) + str(group.group_number)

    return LoginResponse(
        token=token,
        user=LoginUser(
            id=user.id,
            username=user.username,
            first_name=user.first_name,
            middle_name=user.middle_name,
            last_name=user.last_name,
            group=group_name,
        ),
    )


@app.post('/chat', response_model=ChatResponse)
async def chat(
        request: Request,
        data: ChatRequest,
        ai_service: AIContextService = Depends(get_ai_service),
        dialog_service: DialogService = Depends(get_dialog_service)
    ):
    current_user = get_current_user(request)
    user_id = current_user["user_id"]
    user_message = data.message
    user_message_time = datetime.now()

    if data.message == '/task':
        ai_task = await ai_service.start_skill_session(user_id)
        return ChatResponse(message=str(ai_task))

    ai_response = await ai_service.get_response_with_history(user_id=user_id, user_message=user_message)
    ai_response_time = datetime.now()

    await dialog_service.save(
        user_id=user_id, 
        user_message=user_message, 
        ai_response=ai_response,
        question_id=None,
        user_message_time=user_message_time,
        ai_response_time=ai_response_time)

    return ChatResponse(message=ai_response)


@app.get("/chat/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    request: Request,
    dialog_service: DialogService = Depends(get_dialog_service)
    ):
    current_user = get_current_user(request)
    user_id = current_user["user_id"]
    dialogs = await dialog_service.get_user_history(user_id=user_id, limit=1000, question_id=None)
    messages = []
    for dialog in dialogs:
        if dialog.user_message:  
            messages.append(MessageItem(
                id=f"{dialog.id}user",
                role="user",
                content=dialog.user_message,
                timestamp=dialog.user_message_time,
            ))
        if dialog.ai_response:  
            messages.append(MessageItem(
                id=f"{dialog.id}ai",
                role="ai",
                content=dialog.ai_response,
                timestamp=dialog.ai_response_time,
            ))
    
    return ChatHistoryResponse(
        user_id=user_id,
        username=current_user["username"],
        messages=messages,
    )