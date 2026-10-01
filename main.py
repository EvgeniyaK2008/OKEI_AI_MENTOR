# main.py
import logging
from dotenv import load_dotenv
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, Request, Depends, Query, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import Config

from infrastructure.database.connection import get_db
from infrastructure.repositories.postgres_user_repository import AsyncPostgresUserRepository
from infrastructure.repositories.postgres_skill_matrix_repository import AsyncPostgresSkillMatrixRepository
from infrastructure.repositories.postgres_student_progress_repository import AsyncPostgresStudentProgressRepository
from infrastructure.repositories.postgres_group_repository import AsyncPostgresGroupRepository
from infrastructure.repositories.postgres_dialog_repository import AsyncPostgresDialogRepository
from infrastructure.repositories.postgres_specialty_repository import AsyncPostgresSpecialtyRepository

from infrastructure.ai.yandex_ai_service import YandexAIMainModelService
from application.services.user_service import UserService
from application.services.dialog_service import DialogService
from application.services.auth import hash_password, verify_password, create_access_token, get_current_user, require_role

from application.interactors.start_skill_session import StartSkillSession
from application.interactors.get_skill_for_student import GetSkillForStudent
from application.interactors.get_chat_response import GetChatResponseWithContext, UserMessage, GetChatResponseWithContextResponse
from application.interactors.evaluate_student_answer import EvaluateStudentAnswer, EvaluateStudentAnswerResponse
from application.interactors.detect_student_answer import DetectStudentsAnswer, DetectStudentsAnswerResponse

from application.interactors.get_streak import GetStreak, GetStreakResponse

from domain.entities.skill_matrix import SkillMatrix
from domain.entities.student_progress import StudentProgress
from domain.entities.user import User
from application.repositories.user_repository import UserRepository
from application.repositories.group_repository import GroupRepository
from application.repositories.specialty_repository import SpecialtyRepository
from application.repositories.skill_matrix_repository import SkillMatrixRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.dialog_repository import DialogRepository
from application.ports.ai.ai_port import AIService


# ============================ Pydantic-модели ============================

class ErrorResponse(BaseModel):
    error: str = Field(description="Описание ошибки", examples=["Username already exists"])


class LoginRequest(BaseModel):
    username: str = Field(examples=["ii"])
    password: str = Field(examples=["ii"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, description="Логин пользователя, уникален", examples=["ivanov"])
    password: str = Field(min_length=8, description="Пароль, хранится только в виде хэша", examples=["supersecret1"])
    group_id: int | None = Field(None, description="ID учебной группы из GET /groups.", examples=[3])
    first_name: str = Field("", description="Имя", examples=["Иван"])
    middle_name: str = Field("", description="Отчество", examples=["Иванович"])
    last_name: str = Field("", description="Фамилия", examples=["Иванов"])
    role: Literal["student", "teacher", "admin"] = Field(
        "student",
        description="Роль пользователя: student (по умолчанию), teacher или admin",
        examples=["student"]
    )


class RegisterResponse(BaseModel):
    user_id: int = Field(examples=[11])
    username: str = Field(examples=["ivanov"])


class UserPublic(BaseModel):
    id: int = Field(examples=[11])
    username: str = Field(examples=["ivanov"])
    first_name: str = Field(examples=["Иван"])
    middle_name: str = Field(examples=["Иванович"])
    last_name: str = Field(examples=["Иванов"])
    group: str = Field(description="Название группы", examples=["2ИИ1"])
    role: str = Field(description="Роль пользователя", examples=["student"])


class LoginResponse(BaseModel):
    token: str = Field(description="JWT Bearer-токен.", examples=["eyJhbGciOiJIUzI1NiIs..."])
    user: UserPublic


class GroupItem(BaseModel):
    id: int = Field(description="ID учебной группы", examples=[3])
    name: str = Field(description="Человекочитаемое имя", examples=["2ИИ1"])


class StreakItem(BaseModel):
    current_streak: int = Field(description="Текущая серия дней", examples=[5])
    longest_streak: int = Field(description="Рекорд серии дней", examples=[12])


class SkillItem(BaseModel):
    id: int = Field(examples=[35])
    name: str = Field(description="Название навыка", examples=["Введение в ИИ"])
    description: str | None = Field(None, description="Критерии освоения")


class ProgressItem(BaseModel):
    skill_id: int = Field(description="ID навыка")
    skill: str = Field(description="Название навыка", examples=["Введение в ИИ"])
    level: int = Field(ge=0, le=100, description="Процент освоения", examples=[50])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000, description="Сообщение ментору", examples=["Объясни, чем список отличается от кортежа"])
    question_id: str | None = Field(None, description="ID практической сессии", examples=["8f2a4c1e-..."])


class ChatResponse(BaseModel):
    message: str = Field(description="Ответ ментора", examples=["Верно мыслишь."])
    question_id: str | None = Field(None, description="ID сессии", examples=["8f2a4c1e-..."])
    assessment: EvaluateStudentAnswerResponse | None = Field(None, description="Результат оценки")


class TaskResponse(BaseModel):
    question: str = Field(description="Текст задания", examples=["Напишите функцию..."])
    question_id: str = Field(description="ID сессии задания", examples=["8f2a4c1e-..."])


class MessageItem(BaseModel):
    id: str = Field(description="Уникальный ключ", examples=["12user"])
    role: Literal["user", "ai"] = Field(description="Автор: user или ai")
    content: str = Field(examples=["Объясни, чем список отличается от кортежа"])
    timestamp: datetime | None = Field(None, description="Время создания")
    question_id: str | None = Field(None, description="ID задания")


class ChatHistoryResponse(BaseModel):
    user_id: int = Field(examples=[11])
    username: str = Field(examples=["ivanov"])
    messages: list[MessageItem] = Field(description="Список сообщений")


# ============================ Приложение ============================

load_dotenv()
config = Config.load()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

bearer_docs = HTTPBearer(auto_error=False)

app = FastAPI(title="AI Mentor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================ ГЛОБАЛЬНАЯ ОБРАБОТКА ОШИБОК ============================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=str(exc.detail)).model_dump()
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    error_msg = exc.errors()[0]["msg"] if exc.errors() else "Ошибка валидации данных"
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error=f"Ошибка валидации: {error_msg}").model_dump()
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Необработанная ошибка на сервере: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error="Внутренняя ошибка сервера. Попробуйте позже.").model_dump()
    )


# ============================ Фабрики зависимостей ============================

async def get_user_repo(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return AsyncPostgresUserRepository(db)

async def get_group_repo(db: AsyncSession = Depends(get_db)) -> GroupRepository:
    return AsyncPostgresGroupRepository(db)

async def get_specialty_repo(db: AsyncSession = Depends(get_db)) -> SpecialtyRepository:
    return AsyncPostgresSpecialtyRepository(db)

async def get_student_progress_repo(db: AsyncSession = Depends(get_db)) -> StudentProgressRepository:
    return AsyncPostgresStudentProgressRepository(db)

async def get_matrix_repo(db: AsyncSession = Depends(get_db)) -> SkillMatrixRepository:
    return AsyncPostgresSkillMatrixRepository(db)

async def get_dialog_repo(db: AsyncSession = Depends(get_db)) -> DialogRepository:
    return AsyncPostgresDialogRepository(db)

async def get_dialog_service(db: AsyncSession = Depends(get_db)) -> DialogService:
    return DialogService(AsyncPostgresDialogRepository(db))

async def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(
        AsyncPostgresUserRepository(db),
        AsyncPostgresSkillMatrixRepository(db),
        AsyncPostgresStudentProgressRepository(db)
    )

async def get_ai_mentor(db: AsyncSession = Depends(get_db)) -> AIService:
    return YandexAIMainModelService(config.mentor_ai)

async def get_ai_secondary(db: AsyncSession = Depends(get_db)) -> AIService:
    return YandexAIMainModelService(config.secondary_ai)

async def get_get_skill_for_student(db: AsyncSession = Depends(get_db)) -> GetSkillForStudent:
    return GetSkillForStudent(
        student_progress_repo=AsyncPostgresStudentProgressRepository(db),
        skill_matrix_repo=AsyncPostgresSkillMatrixRepository(db),
        user_repo=AsyncPostgresUserRepository(db)
    )

async def get_start_skill_session(db: AsyncSession = Depends(get_db)) -> StartSkillSession:
    user_repo = AsyncPostgresUserRepository(db)
    skill_matrix_repo = AsyncPostgresSkillMatrixRepository(db)
    student_progress_repo = AsyncPostgresStudentProgressRepository(db)
    specialty_repo = AsyncPostgresSpecialtyRepository(db)
    dialog_repo = AsyncPostgresDialogRepository(db)
    group_repo = AsyncPostgresGroupRepository(db)

    return StartSkillSession(
        ai_service=YandexAIMainModelService(config.mentor_ai),
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

async def get_evaluate_student_answer(db: AsyncSession = Depends(get_db)) -> EvaluateStudentAnswer:
    dialog_repo = AsyncPostgresDialogRepository(db)
    student_progress_repo = AsyncPostgresStudentProgressRepository(db)
    skill_matrix_repo = AsyncPostgresSkillMatrixRepository(db)
    user_repo = AsyncPostgresUserRepository(db)

    return EvaluateStudentAnswer(
        dialog_service=DialogService(dialog_repo),
        student_progress_repo=student_progress_repo,
        get_skill_for_student=GetSkillForStudent(
            student_progress_repo=student_progress_repo,
            skill_matrix_repo=skill_matrix_repo,
            user_repo=user_repo
        ),
        dialog_repo=dialog_repo,
        ai_service=YandexAIMainModelService(config.secondary_ai),
        user_repo=user_repo,
    )

async def get_detect_students_answer(db: AsyncSession = Depends(get_db)) -> DetectStudentsAnswer:
    return DetectStudentsAnswer(
        ai_service=YandexAIMainModelService(config.secondary_ai),
        dialog_repo=AsyncPostgresDialogRepository(db)
    )

async def get_user_streak(db: AsyncSession = Depends(get_db)) -> GetStreak:
    return GetStreak(
        user_repo=AsyncPostgresUserRepository(db)
    )


# ============================ Роуты ============================

# Обычная авторизация (любая роль может смотреть свой профиль)
@app.get('/me', response_model=UserPublic, tags=["auth"], dependencies=[Depends(bearer_docs)],
         summary="Текущий пользователь")
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
        id=user.id, username=user.username, first_name=user.first_name or "",
        middle_name=user.middle_name or "", last_name=user.last_name or "", 
        group=group_name, role=user.role
    )


@app.post("/login", response_model=LoginResponse, tags=["auth"],
          summary="Вход и получение токена")
async def login_page(
    data: LoginRequest,
    user_repo: UserRepository = Depends(get_user_repo),
    group_repo: GroupRepository = Depends(get_group_repo),
    specialty_repo: SpecialtyRepository = Depends(get_specialty_repo),
):
    user = await user_repo.find_by_username(data.username)
    if not user or not verify_password(data.password, user.hashed_password):
        return JSONResponse(status_code=401, content=ErrorResponse(error="Invalid credentials").model_dump())

    token = create_access_token(
        data={"username": user.username, "user_id": user.id},
        role=user.role.value if hasattr(user.role, 'value') else user.role
    )
    group_name = ""
    if user.group is not None:
        group = await group_repo.find_by_id(user.group.id)
        specialty = await specialty_repo.find_by_id(group.specialty.id)
        group_name = str(group.year) + str(specialty.short_name) + str(group.group_number)

    return LoginResponse(
        token=token,
        user=UserPublic(id=user.id, username=user.username, first_name=user.first_name or "",
                        middle_name=user.middle_name or "", last_name=user.last_name or "", 
                        group=group_name, role=user.role),
    )


@app.post("/register", response_model=RegisterResponse, status_code=201, tags=["auth"],
          summary="Регистрация пользователя")
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
        username=data.username, hashed_password=hash_password(data.password),
        first_name=data.first_name, middle_name=data.middle_name, last_name=data.last_name,
        group=group, role=data.role,
    )
    return RegisterResponse(user_id=user.id, username=user.username)


# !!! ДВОЙНАЯ ЗАЩИТА: И авторизация, И проверка роли !!!
@app.get("/skills", response_model=list[SkillItem], tags=["study"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Каталог навыков")
async def get_skills(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repo),
    matrix_repo: SkillMatrixRepository = Depends(get_matrix_repo),
):
    user_id = get_current_user(request)["user_id"]
    user: User = await user_repo.find_by_id(user_id)
    course: int = user.get_course()
    specialty_id: int = user.get_specialty_id()
    matrices = await matrix_repo.find_by_course_and_specialty(course, specialty_id)
    return [SkillItem(id=m.id, name=m.skill, description=m.criterions) for m in matrices]


@app.get("/progress", response_model=list[ProgressItem], tags=["study"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Прогресс студента")
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
        result.append(ProgressItem(skill_id=el.skill_id, skill=skill.skill, level=el.level))
    return result


@app.get("/groups", response_model=list[GroupItem], tags=["study"],
         summary="Список учебных групп")
async def get_groups(group_repo: AsyncPostgresGroupRepository = Depends(get_group_repo)):
    groups = await group_repo.find_active_groups()
    return [
        GroupItem(id=g.id, name=f"{datetime.now().year - g.year + 1}{g.specialty.short_name}{g.group_number}")
        for g in groups
    ]


@app.get('/streak', response_model=StreakItem, tags=["study"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Стрик пользователя")
async def get_streak(
    request: Request,
    use_case: GetStreak = Depends(get_user_streak)
):
    user_id = get_current_user(request)["user_id"]
    result: GetStreakResponse = await use_case.execute(user_id)

    return StreakItem(
        current_streak=result.current_streak,
        longest_streak=result.longest_streak
    )


@app.post("/task", response_model=TaskResponse, tags=["chat"], 
          dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
          summary="Начать практическую сессию")
async def start_task(
    request: Request,
    task_case: StartSkillSession = Depends(get_start_skill_session),
):
    user_id = get_current_user(request)["user_id"]
    result = await task_case.execute(user_id)
    return TaskResponse(question=result.question, question_id=result.question_id)


@app.get("/task/current", response_model=TaskResponse | None, tags=["chat"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Текущее активное задание")
async def get_current_task(
    request: Request,
    dialog_repo: DialogRepository = Depends(get_dialog_repo)
):
    user_id = get_current_user(request)["user_id"]
    last_dialog = await dialog_repo.get_last_task_dialog(user_id=user_id)

    if not last_dialog or not last_dialog.ai_response:
        return None

    return TaskResponse(
        question=last_dialog.ai_response,
        question_id=last_dialog.question_id
    )


@app.post("/chat", response_model=ChatResponse, tags=["chat"], 
          dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
          summary="Сообщение ментору")
async def chat(
    request: Request,
    data: ChatRequest,
    dialog_service: DialogService = Depends(get_dialog_service),
    ai_service: AIService = Depends(get_ai_mentor),
    detection_case: DetectStudentsAnswer = Depends(get_detect_students_answer),
    evaluate_case: EvaluateStudentAnswer = Depends(get_evaluate_student_answer)
):
    user_id: int = get_current_user(request)["user_id"]
    user_message = UserMessage(user_id=user_id, message=data.message)
    user_message_time: datetime = datetime.now()
    assessment = None

    if data.question_id:
        answer_detected: DetectStudentsAnswerResponse = await detection_case.execute(data.question_id)
        if answer_detected.answer_found:
            assessment = await evaluate_case.execute(data.question_id)

    use_case = GetChatResponseWithContext()
    result: GetChatResponseWithContextResponse = await use_case.execute(
        user_message=user_message,
        dialog_service=dialog_service,
        ai_service=ai_service
    )
    ai_response_time: datetime = datetime.now()

    await dialog_service.save(
        user_id=user_id,
        user_message=data.message,
        ai_response=result.response,
        question_id=data.question_id,
        user_message_time=user_message_time,
        ai_response_time=ai_response_time,
    )

    return ChatResponse(
        message=result.response,
        question_id=data.question_id,
        assessment=assessment
    )


@app.get("/chat/history", response_model=ChatHistoryResponse, tags=["chat"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="История диалога")
async def get_chat_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="Сколько сообщений вернуть"),
    dialog_service: DialogService = Depends(get_dialog_service),
):
    current_user = get_current_user(request)
    user_id = current_user["user_id"]

    dialogs = await dialog_service.get_user_history(user_id=user_id, limit=limit, question_id=None)

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
    messages.reverse()

    return ChatHistoryResponse(user_id=user_id, username=current_user["username"], messages=messages)