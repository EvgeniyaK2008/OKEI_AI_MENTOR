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
from application.interactors.get_admin_stats import GetAdminStats
from admin_panel import *
from sqladmin import Admin
from infrastructure.database.connection import sync_engine

from domain.entities.skill_matrix import SkillMatrix
from domain.entities.student_progress import StudentProgress
from domain.entities.user import User
from application.repositories.user_repository import UserRepository
from application.repositories.group_repository import GroupRepository
from application.repositories.specialty_repository import SpecialtyRepository
from application.repositories.skill_matrix_repository import SkillMatrixRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.dialog_repository import DialogRepository
from application.repositories.stats_repository import StatsRepository
from application.ports.ai.ai_port import AIService
from infrastructure.repositories.postgres_stats_repository import AsyncPostgresStatsRepository


# ============================ Pydantic-модели ============================

class SkillStatsItem(BaseModel):
    skill_id: int = Field(description="ID навыка", examples=[19])
    skill: str = Field(description="Название навыка", examples=["Оптимизация гиперпараметров"])
    avg_level: float = Field(description="Средний процент освоения навыка среди студентов", examples=[61.3])
    students_count: int = Field(description="Количество студентов, у которых есть этот навык", examples=[26])


class GroupActivityItem(BaseModel):
    group_id: int = Field(description="ID группы", examples=[1])
    group_name: str = Field(description="Название группы", examples=["3ии1"])
    total_messages: int = Field(description="Общее количество сообщений в группе", examples=[1057])
    total_tasks: int = Field(description="Общее количество выданных заданий в группе", examples=[694])


class GroupTasksItem(BaseModel):
    group_id: int = Field(description="ID группы", examples=[1])
    group_name: str = Field(description="Название группы", examples=["3ии1"])
    completed_tasks: int = Field(description="Количество выполненных заданий", examples=[694])
    active_students: int = Field(description="Количество студентов, выполнивших хотя бы одно задание", examples=[30])


class DailyActivityItem(BaseModel):
    day: str = Field(description="Дата в формате YYYY-MM-DD", examples=["2026-10-05"])
    group_id: int = Field(description="ID группы", examples=[1])
    group_name: str = Field(description="Название группы", examples=["3ии1"])
    messages_count: int = Field(description="Количество сообщений в этот день", examples=[14])


class AdminStatsResponse(BaseModel):
    total_students: int = Field(description="Общее количество студентов")
    active_groups_count: int = Field(description="Количество активных групп")
    avg_progress_by_skill: list[SkillStatsItem] = Field(description="Средний прогресс по каждому навыку")
    weakest_skills: list[SkillStatsItem] = Field(description="Топ-5 самых слабых навыков")
    activity_by_group: list[GroupActivityItem] = Field(description="Активность групп: сообщения и задания")
    completed_tasks_by_group: list[GroupTasksItem] = Field(description="Решённые задания по группам")
    daily_activity: list[DailyActivityItem] = Field(description="Ежедневная активность для тепловой карты")


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
    role: Literal["student", "teacher", "manager", "admin"] = Field(
        "student",
        description="Роль пользователя: student (по умолчанию), teacher или manager",
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
    current_streak: int = Field(description="Текущая серия дней выполнения заданий", examples=[5])
    longest_streak: int = Field(description="Рекорд серии дней", examples=[12])


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
    weaknesses: str | None = Field(None, description="Слабые места студента в теме", examples=["Не понимает синтаксис функций"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000, description="Сообщение ментору", examples=["Объясни, чем список отличается от кортежа"])
    question_id: str | None = Field(
        None, 
        description="ID практической сессии из POST /task. Если передан, сообщение считается ответом на задание и запускает оценку. Если null — обычный чат.", 
        examples=["8f2a4c1e-..."]
    )


class ChatResponse(BaseModel):
    message: str = Field(description="Ответ ментора", examples=["Верно мыслишь."])
    question_id: str | None = Field(None, description="ID сессии", examples=["8f2a4c1e-..."])
    assessment: EvaluateStudentAnswerResponse | None = Field(
        None, 
        description="Результат оценки (level, feedback, skill_id). Если присутствует, задание считается выполненным."
    )
    task_completed: bool = Field(
        False, 
        description="True, если задание оценено и закрыто. Фронтенд должен сбросить активный question_id."
    )


class TaskResponse(BaseModel):
    question: str = Field(description="Текст задания", examples=["Напишите функцию..."])
    question_id: str = Field(description="ID сессии задания", examples=["8f2a4c1e-..."])


class MessageItem(BaseModel):
    id: str = Field(description="Уникальный ключ", examples=["12user"])
    role: Literal["user", "ai"] = Field(description="Автор: user или ai")
    content: str = Field(examples=["Объясни, чем список отличается от кортежа"])
    timestamp: datetime | None = Field(
        None, 
        description="Время создания сообщения. Null только у служебных записей (например, у выданного задания без ответа студента)."
    )
    question_id: str | None = Field(None, description="ID задания, если сообщение к нему относится")


class ChatHistoryResponse(BaseModel):
    user_id: int = Field(examples=[11])
    username: str = Field(examples=["ivanov"])
    messages: list[MessageItem] = Field(
        description="Список сообщений, отсортированных хронологически (старые сверху, новые снизу)."
    )


# ============================ Приложение ============================
 
config = Config.load()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

bearer_docs = HTTPBearer(auto_error=False)

app = FastAPI(
    title="AI Mentor",
    servers=[
        {"url": "http://ai-mentor.tw1.ru:8000", "description": "Продакшн сервер"},
        {"url": "http://127.0.0.1:8000"}
    ]
)

origins = [
    "http://127.0.0.1:8000",
    "http://localhost:8080",
    "http://ai-mentor.tw1.ru"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_admin(app)

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

async def get_stats_repo(db: AsyncSession = Depends(get_db)) -> StatsRepository:
    return AsyncPostgresStatsRepository(db)

async def get_admin_stats(stats_repo: StatsRepository = Depends(get_stats_repo)) -> GetAdminStats:
    return GetAdminStats(stats_repo=stats_repo)

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
    return GetStreak(user_repo=AsyncPostgresUserRepository(db))


# ============================ Роуты ============================

@app.get(
    "/manager/stats",
    response_model=AdminStatsResponse,
    tags=["stats"],
    dependencies=[Depends(bearer_docs), Depends(require_role("manager"))],
    summary="Статистика для администратора",
    description="Полная статистика по студентам, группам, навыкам и активности за указанный период.",
)
async def get_admin_stats_endpoint(
    days: int = Query(30, ge=1, le=365, description="Период для daily_activity в днях"),
    use_case: GetAdminStats = Depends(get_admin_stats),
):
    result = await use_case.execute(days=days)
    return AdminStatsResponse(
        total_students=result.total_students,
        active_groups_count=result.active_groups_count,
        avg_progress_by_skill=result.avg_progress_by_skill,
        weakest_skills=result.weakest_skills,
        activity_by_group=result.activity_by_group,
        completed_tasks_by_group=result.completed_tasks_by_group,
        daily_activity=result.daily_activity,
    )


@app.get('/me', response_model=UserPublic, tags=["auth"], dependencies=[Depends(bearer_docs)],
         summary="Текущий пользователь", 
         description="Возвращает профиль текущего пользователя по JWT-токену: ID, логин, ФИО, группа, роль и стрик.")
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
        group=group_name, 
        role=user.role.value if hasattr(user.role, 'value') else user.role,
        current_streak=user.current_streak,
        longest_streak=user.longest_streak,
    )


@app.post("/login", response_model=LoginResponse, tags=["auth"],
          summary="Вход и получение токена",
          description="Проверяет логин/пароль и выдаёт JWT вместе с профилем пользователя.",
          responses={
              401: {"model": ErrorResponse, "description": "Неверный логин или пароль"},
              422: {"model": ErrorResponse, "description": "Ошибка валидации данных"}
          })
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
        user=UserPublic(
            id=user.id, username=user.username, first_name=user.first_name or "",
            middle_name=user.middle_name or "", last_name=user.last_name or "", 
            group=group_name, 
            role=user.role.value if hasattr(user.role, 'value') else user.role,
            current_streak=user.current_streak,
            longest_streak=user.longest_streak,
        ),
    )


@app.post("/register", response_model=RegisterResponse, status_code=201, tags=["auth"],
          summary="Регистрация пользователя",
          description="Создаёт нового пользователя. Роль назначается через параметр (по умолчанию student). Ошибка 409 — логин уже занят.",
          responses={
              409: {"model": ErrorResponse, "description": "Username уже занят"},
              422: {"model": ErrorResponse, "description": "Ошибка валидации данных"}
          })
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


@app.get("/skills", response_model=list[SkillItem], tags=["study"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Каталог навыков",
         description="Возвращает все навыки матрицы компетенций для курса и специальности текущего студента.")
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
         summary="Прогресс студента",
         description="Возвращает проценты освоения навыков (0–100) и слабые места по каждому навыку. Обновляется после оценки задания.")
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
        result.append(ProgressItem(
            skill_id=el.skill_id, 
            skill=skill.skill, 
            level=el.level,
            weaknesses=el.weaknesses
        ))
    return result


@app.get("/groups", response_model=list[GroupItem], tags=["study"],
         summary="Список учебных групп",
         description="Активные группы колледжа для выбора при регистрации.")
async def get_groups(group_repo: AsyncPostgresGroupRepository = Depends(get_group_repo)):
    groups = await group_repo.find_active_groups()
    return [
        GroupItem(id=g.id, name=f"{datetime.now().year - g.year + 1}{g.specialty.short_name}{g.group_number}")
        for g in groups
    ]


@app.get('/streak', response_model=StreakItem, tags=["study"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Стрик пользователя",
         description="Возвращает текущую и максимальную серию дней выполнения заданий. Обновляется автоматически при успешной оценке задания.")
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
          summary="Начать практическую сессию",
          description="Ментор генерирует НОВОЕ задание при каждом вызове. Задание подбирается под самый слабый навык студента.",
          responses={
              401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"},
              500: {"model": ErrorResponse, "description": "Внутренняя ошибка или недоступность AI"},
              503: {"model": ErrorResponse, "description": "Нет доступных навыков для генерации задания"}
          })
async def start_task(
    request: Request,
    task_case: StartSkillSession = Depends(get_start_skill_session),
):
    user_id = get_current_user(request)["user_id"]
    result = await task_case.execute(user_id)
    return TaskResponse(question=result.question, question_id=result.question_id)


@app.get("/task/current", response_model=TaskResponse | None, tags=["chat"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Текущее активное задание",
         description="Возвращает последнее выданное задание, если оно есть. Если активного задания нет, возвращает null. Используется для восстановления состояния после перезагрузки страницы.",
         responses={401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"}})
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
          summary="Сообщение ментору",
          description="Единственный диалог студента с ментором. Если передан question_id, сообщение считается ответом на задание и запускает ИИ-детектор. Если детектор распознаёт ответ, запускается оценка (прогресс и стрик обновляются автоматически). Если assessment не null — задание считается выполненным, фронтенд должен сбросить активный question_id.",
          responses={
              401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"},
              422: {"model": ErrorResponse, "description": "Ошибка валидации (например, слишком длинное сообщение)"},
              500: {"model": ErrorResponse, "description": "Ошибка AI или БД"}
          })
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
        assessment=assessment,
        task_completed=assessment is not None
    )


@app.get("/chat/history", response_model=ChatHistoryResponse, tags=["chat"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="История диалога",
         description="Возвращает последние N сообщений, отсортированных хронологически (старые сверху, новые снизу). Параметр limit ограничивает количество возвращаемых сообщений (по умолчанию 50, максимум 200).",
         responses={
             401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"},
             422: {"model": ErrorResponse, "description": "Ошибка валидации параметра limit"}
         })
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


