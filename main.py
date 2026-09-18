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

from application.use_cases.start_skill_session import StartSkillSession

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

from fastapi import FastAPI, Request, Form, Depends, Response, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from typing import Optional, Any, List, Literal

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


class ErrorResponse(BaseModel):
    error: str = Field(description="Человекочитаемое описание ошибки", examples=["Username already exists"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, description="Логин студента, уникален", examples=["ivanov"])
    password: str = Field(min_length=8, description="Пароль, хранится только в виде хэша", examples=["supersecret1"])
    group_id: int | None = Field(None, description="ID учебной группы из GET /groups. Если не указан студент без группы", examples=[3])
    first_name: str = Field("", description="Обязательно при регистрации, можно оставить пустым", examples=["Иван"])
    middle_name: str = Field("", description="обязательно при регистрации", examples=["Иванович"])
    last_name: str = Field("", description="Необязательно при регистрации", examples=["Иванов"])


class RegisterResponse(BaseModel):
    user_id: int = Field(examples=[11])
    username: str = Field(examples=["ivanov"])


class UserPublic(BaseModel):
    id: int = Field(examples=[11])
    username: str = Field(examples=["ivanov"])
    first_name: str = Field(examples=["Иван"])
    middle_name: str = Field(examples=["Иванович"])
    last_name: str = Field(examples=["Иванов"])
    group: str = Field(description="Название группы в формате <курс><специальность><номер>; пустая строка если группы нет", examples=["2ИИ1"])


class LoginResponse(BaseModel):
    token: str = Field(description="JWT Bearer-токен. Передавать в заголовке Authorization: Bearer <token>. Refresh-токена нет: после истечения срока жизни (задаётся в create_access_token) нужен повторный POST /login", examples=["eyJhbGciOiJIUzI1NiIs..."])
    user: UserPublic


class GroupItem(BaseModel):
    id: int = Field(description="ID учебной группы; передаётся в group_id при регистрации", examples=[3])
    name: str = Field(description="Человекочитаемое имя: <курс><сокращение специальности><номер группы>", examples=["2ИИ1"])


class SkillItem(BaseModel):
    id: int = Field(examples=[35])
    name: str = Field(description="Название навыка из матрицы компетенций", examples=["Введение в ИИ и машинное обучение"])
    description: str | None = Field(None, description="Критерии освоения навыка из матрицы компетенций")


class ProgressItem(BaseModel):
    skill: str = Field(description="Название навыка из матрицы компетенций", examples=["Введение в ИИ и машинное обучение"])
    level: int = Field(ge=0, le=100, description="Процент освоения навыка, 0–100. Пересчитывается после проверки практических заданий; для нового пользователя прогресс пуст", examples=[50])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000, description="Сообщение ментору. Ментор отвечает наводящими вопросами и подсказками, а не готовым решением. Для получения практического задания -POST /task", examples=["Объясни, чем список отличается от кортежа в Python"])


class ChatResponse(BaseModel):
    message: str = Field(description="Ответ ментора: наводящий вопрос, подсказка или разбор попытки", examples=["Верно мыслишь. А что произойдёт с кортежем, если попробовать добавить в него элемент?"])
    question_id: str | None = Field(None, description="ID практической сессии (POST /task), если ответ относится к заданию; в свободном диалоге - null", examples=["8f2a4c1e-..."])


class TaskResponse(BaseModel):
    question: str = Field(description="Текст практического задания, подобранного под слабый навык, специальность и курс студента", examples=["Напишите функцию, которая... Критерии оценки: ..."])
    question_id: str = Field(description="ID сессии задания; им помечаются записи истории, относящиеся к заданию", examples=["8f2a4c1e-..."])


class MessageItem(BaseModel):
    id: str = Field(description="Уникальный ключ сообщения для рендера списка", examples=["12user"])
    role: Literal["user", "ai"] = Field(description="Автор сообщения: user - студент, ai - ментор")
    content: str = Field(examples=["Объясни, чем список отличается от кортежа"])
    timestamp: datetime | None = Field(None, description="Время создания; null у служебных записей (например, у выданного задания без ответа студента)")


class ChatHistoryResponse(BaseModel):
    user_id: int = Field(examples=[11])
    username: str = Field(examples=["ivanov"])
    messages: list[MessageItem] = Field(description="Хронологический список сообщений единственного диалога студента с ментором. У нового пользователя - пустой массив")


load_dotenv()
config = Config.load()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from fastapi.security import HTTPBearer

bearer_docs = HTTPBearer(auto_error=False)

app = FastAPI(
    title="AI Mentor"
)

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

async def get_start_skill_session(db: AsyncSession = Depends(get_db)):
    user_repo = AsyncPostgresUserRepository(db)
    skill_matrix_repo = AsyncPostgresSkillMatrixRepository(db)
    student_progress_repo = AsyncPostgresStudentProgressRepository(db)
    specialty_repo = AsyncPostgresSpecialtyRepository(db)
    dialog_repo = AsyncPostgresDialogRepository(db)
    group_repo = AsyncPostgresGroupRepository(db)
    return StartSkillSession(
        ai_service=YandexAIService(config),
        dialog_service=DialogService(dialog_repo),
        user_repo=user_repo,
        get_skill_for_student=GetSkillForStudent(
            student_progress_repo=student_progress_repo,
            skill_matrix_repo=skill_matrix_repo,
            user_repo=user_repo,
        ),
        student_progress_repo=student_progress_repo,
        specialty_repo=specialty_repo,
        group_repo=group_repo
    )

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


@app.get(
    '/me',
    response_model=UserPublic,
    tags=["auth"],
    dependencies=[Depends(bearer_docs)],
    summary="Текущий пользователь",
    description="Профиль по токену: кто и в какой группе.",
    responses={401: {"model": ErrorResponse, "description": "Нет токена или токен недействителен"}},
    )
async def get_me(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repo),
    group_repo: GroupRepository = Depends(get_group_repo),
    specialty_repo: SpecialtyRepository = Depends(get_specialty_repo),
):
    user_id = get_current_user(request)["user_id"]
    user = await user_repo.find_by_id(user_id)
    group_name = ""
    if user.group is not None:
        group = await group_repo.find_by_id(user.group.id)
        specialty = await specialty_repo.find_by_id(group.specialty.id)
        group_name = str(group.year) + str(specialty.short_name) + str(group.group_number)
    return UserPublic(
        id=user.id,
        username=user.username,
        first_name=user.first_name or "",
        middle_name=user.middle_name or "",
        last_name=user.last_name or "",
        group=group_name,
    )

@app.post(
    "/login",
    response_model=LoginResponse,
    tags=["auth"],
    summary="Вход и получение токена",
    description="Проверяет логин/пароль и выдаёт JWT вместе с профилем. Ошибка 401 — неверные учётные данные.",
    responses={401: {"model": ErrorResponse, "description": "Неверный логин или пароль"}},
)
async def login_page(
    data: LoginRequest,
    user_repo: UserRepository = Depends(get_user_repo),
    group_repo: GroupRepository = Depends(get_group_repo),
    specialty_repo: SpecialtyRepository = Depends(get_specialty_repo),
):
    user = await user_repo.find_by_username(data.username)
    if not user or not verify_password(data.password, user.hashed_password):
        return JSONResponse(status_code=401, content=ErrorResponse(error="Invalid credentials").model_dump())

    token = create_access_token({"username": user.username, "user_id": user.id})
    group_name = ""
    if user.group is not None:
        group = await group_repo.find_by_id(user.group.id)
        specialty = await specialty_repo.find_by_id(group.specialty.id)
        group_name = str(group.year) + str(specialty.short_name) + str(group.group_number)

    return LoginResponse(
        token=token,
        user=UserPublic(
            id=user.id,
            username=user.username,
            first_name=user.first_name or "",
            middle_name=user.middle_name or "",
            last_name=user.last_name or "",
            group=group_name,
        ),
    )


@app.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    tags=["auth"],
    summary="Регистрация студента",
    description="Создаёт пользователя. Имена необязательны. Ошибка 409 — логин уже занят.",
    responses={409: {"model": ErrorResponse, "description": "Username уже занят"}},
)
async def register(
    data: RegisterRequest,
    service: UserService = Depends(get_user_service),
    user_repo: UserRepository = Depends(get_user_repo),
    group_repo: GroupRepository = Depends(get_group_repo),
):
    existing = await user_repo.find_by_username(data.username)
    if existing:
        return JSONResponse(status_code=409, content=ErrorResponse(error="Username already exists").model_dump())

    group = None
    if data.group_id:
        group = await group_repo.find_by_id(int(data.group_id))

    user = await service.get_or_create_user(
        username=data.username,
        hashed_password=hash_password(data.password),
        first_name=data.first_name,
        middle_name=data.middle_name,
        last_name=data.last_name,
        group=group,
    )
    return RegisterResponse(user_id=user.id, username=user.username)


@app.get(
    "/skills",
    response_model=list[SkillItem],
    dependencies=[Depends(bearer_docs)],
    tags=["study"],
    summary="Каталог навыков",
    description="Все навыки матриц компетенций. Персональный прогресс по ним — GET /progress.",
)
async def get_skills(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repo),
    matrix_repo: SkillMatrixRepository = Depends(get_matrix_repo),
    student_progress_repo: StudentProgressRepository = Depends(get_student_progress_repo)
    ):
    user_id = get_current_user(request)["user_id"]
    user: User = await user_repo.find_by_id(user_id)
    course: int = user.get_course()
    specialty_id: int = user.get_specialty_id()
    matrices = await matrix_repo.find_by_course_and_specialty(course, specialty_id) 
    return [SkillItem(id=m.id, name=m.skill, description=m.criterions) for m in matrices]


@app.get(
    "/progress",
    response_model=list[ProgressItem],
    tags=["study"],
    dependencies=[Depends(bearer_docs)],
    summary="Прогресс студента",
    description="Проценты освоения навыков (0–100) текущего пользователя. У нового пользователя — пустой массив. Ошибка 401 — нет токена.",
    responses={401: {"model": ErrorResponse}},
)
async def get_progress(
    request: Request,
    student_progress_repo: StudentProgressRepository = Depends(get_student_progress_repo),
    matrix_repo: SkillMatrixRepository = Depends(get_matrix_repo),
):
    user_id = get_current_user(request)["user_id"]
    student_progress: list[StudentProgress] = await student_progress_repo.find_by_student_id(user_id)

    result = []
    for el in student_progress:
        skill: SkillMatrix = await matrix_repo.find_by_id(el.skill_id)
        result.append(ProgressItem(skill=skill.skill, level=el.level))
    return result


@app.get(
    "/groups",
    response_model=list[GroupItem],
    tags=["study"],
    summary="Список учебных групп",
    description="Активные группы колледжа для выбора при регистрации. Группа определяет специальность (набор навыков) и курс (сложность заданий). Смена группы студентом не предусмотрена.",
)
async def get_groups(group_repo: AsyncPostgresGroupRepository = Depends(get_group_repo)):
    groups = await group_repo.find_active_groups()

    return [
        GroupItem(id=g.id, name=f"{datetime.now().year - g.year + 1}{g.specialty.short_name}{g.group_number}")
        for g in groups
    ]

@app.post(
    "/task",
    response_model=TaskResponse,
    tags=["chat"],
    dependencies=[Depends(bearer_docs)],
    summary="Начать практическую сессию",
    description="Ментор находит навык с наибольшим дефицитом и генерирует практическое задание под специальность и курс студента. Задание также сохраняется в историю с question_id. Ответ студента принимается через POST /chat. Ошибка 401 — нет токена.",
    responses={401: {"model": ErrorResponse}},
)
async def start_task(
    request: Request,
    use_case: StartSkillSession = Depends(get_start_skill_session),
):
    user_id = get_current_user(request)["user_id"]
    result = await use_case.execute(user_id)
    return TaskResponse(question=result.question, question_id=result.question_id)


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chat"],
    dependencies=[Depends(bearer_docs)],
    summary="Сообщение ментору",
    description="Единственный диалог студента с ментором. Ментор отвечает наводящими вопросами и подсказками, а не готовым решением. Для получения задания используй POST /task, а не команды в тексте. Ошибка 401 — нет токена.",
    responses={401: {"model": ErrorResponse}},
)
async def chat(
    request: Request,
    data: ChatRequest,
    ai_service: AIContextService = Depends(get_ai_service),
    dialog_service: DialogService = Depends(get_dialog_service),
):
    user_id = get_current_user(request)["user_id"]
    now = datetime.now()

    ai_response = await ai_service.get_response_with_history(user_id=user_id, user_message=data.message)
    await dialog_service.save(
        user_id=user_id,
        user_message=data.message,
        ai_response=ai_response,
        question_id=None,
        user_message_time=now,
        ai_response_time=datetime.now(),
    )
    return ChatResponse(message=ai_response, question_id=None)


@app.get(
    "/chat/history",
    response_model=ChatHistoryResponse,
    tags=["chat"],
    dependencies=[Depends(bearer_docs)],
    summary="История диалога",
    description="Хронологическая история единственного диалога студента с ментором, включая выданные задания. У нового пользователя messages — пустой массив. Пагинация: limit (курсорная — в roadmap). Ошибка 401 — нет токена.",
    responses={401: {"model": ErrorResponse}},
)
async def get_chat_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="Сколько сообщений вернуть, не более 200"),
    dialog_service: DialogService = Depends(get_dialog_service),
):
    current_user = get_current_user(request)
    user_id = current_user["user_id"]
    dialogs = await dialog_service.get_user_history(user_id=user_id, limit=limit, question_id=None)

    messages = []
    for dialog in dialogs:
        if dialog.user_message:
            messages.append(MessageItem(id=f"{dialog.id}", role="user", content=dialog.user_message, timestamp=dialog.user_message_time))
        if dialog.ai_response:
            messages.append(MessageItem(id=f"{dialog.id}", role="ai", content=dialog.ai_response, timestamp=dialog.ai_response_time))

    return ChatHistoryResponse(user_id=user_id, username=current_user["username"], messages=messages)
