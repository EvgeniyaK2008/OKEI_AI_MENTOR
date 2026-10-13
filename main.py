# main.py
import logging
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, Request, Depends, Query, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from application.interactors.authenticate_user import AuthenticateUser
from application.interactors.get_chat_history import GetChatHistory
from application.interactors.get_user_info import GetUserProfile
from application.interactors.process_chat_message import ChatRequestData, ProcessChatMessage
from application.interactors.register_user import RegisterRequestData, RegisterUser
from config.config import Config

from application.services.auth import get_current_user, require_role

from application.interactors.start_skill_session import StartSkillSession

from application.interactors.get_streak import GetStreak, GetStreakResponse
from application.interactors.get_admin_stats import GetAdminStats
from infrastructure.repositories.postgres_group_repository import AsyncPostgresGroupRepository
from presentation.web.fastapi.admin_panel import *

from domain.entities.skill_matrix import SkillMatrix
from domain.entities.student_progress import StudentProgress
from domain.entities.user import User
from application.repositories.user_repository import UserRepository
from application.repositories.skill_matrix_repository import SkillMatrixRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.dialog_repository import DialogRepository
from infrastructure.dependency_fabrics import get_container
from presentation.web.fastapi.models import *


# ============================ Приложение ============================

CurrentUser = Annotated[dict, Depends(get_current_user)]
StudentUser = Annotated[dict, Depends(require_role("student"))]
ManagerUser = Annotated[dict, Depends(require_role("manager"))]

config = Config.load()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ЭТОТ ОБЪЕКТ ОТВЕЧАЕТ ЗА КНОПКУ "AUTHORIZE" В SWAGGER
bearer_docs = HTTPBearer(auto_error=False)
container = get_container()

app = FastAPI(
    title="AI Mentor",
    servers=[
        {"url": "http://ai-mentor.tw1.ru:8000", "description": "Продакшн сервер"},
        {"url": "http://127.0.0.1:8000", "description": "Локальный сервер"}
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
    use_case: GetAdminStats = Depends(container.get_admin_stats),
):
    result = await use_case.execute(days=days)
    return result


@app.get(
    '/me', 
    response_model=UserPublic, 
    tags=["auth"],
    dependencies=[Depends(bearer_docs)] 
)
async def get_me(
    current_user: CurrentUser,
    use_case: GetUserProfile = Depends(container.get_user_profile) 
):
    return await use_case.execute(user_id=current_user["user_id"])


@app.post("/login", response_model=LoginResponse, tags=["auth"])
async def login_page(
    data: LoginRequest,
    use_case: AuthenticateUser = Depends(container.get_authenticate_user) 
):
    return await use_case.execute(username=data.username, password=data.password)


@app.post("/register", response_model=RegisterResponse, status_code=201, tags=["auth"])
async def register(
    data: RegisterRequest,
    use_case: RegisterUser = Depends(container.get_register_user) 
):
    request_data = RegisterRequestData(
        username=data.username, password=data.password, group_id=data.group_id,
        first_name=data.first_name, middle_name=data.middle_name, last_name=data.last_name
    )
    result = await use_case.execute(request_data)
    return RegisterResponse(user_id=result.user_id, username=result.username)


@app.get(
    "/skills", 
    response_model=list[SkillItem], 
    tags=["study"],
    dependencies=[Depends(bearer_docs)], 
    summary="Каталог навыков",
    description="Возвращает все навыки матрицы компетенций для курса и специальности текущего студента."
)
async def get_skills(
    user: StudentUser,
    user_repo: UserRepository = Depends(container.get_user_repo),
    matrix_repo: SkillMatrixRepository = Depends(container.get_matrix_repo),
):
    user_id = user["user_id"]
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
    description="Возвращает проценты освоения навыков (0–100) и слабые места по каждому навыку. Обновляется после оценки задания."
)
async def get_progress(
    student: StudentUser,
    student_progress_repo: StudentProgressRepository = Depends(container.get_student_progress_repo),
    matrix_repo: SkillMatrixRepository = Depends(container.get_matrix_repo),
):
    user_id = student["user_id"]
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


@app.get(
    "/groups", 
    response_model=list[GroupItem], 
    tags=["study"],
    summary="Список учебных групп",
    description="Активные группы колледжа для выбора при регистрации."
)
async def get_groups(group_repo: AsyncPostgresGroupRepository = Depends(container.get_group_repo)):
    groups = await group_repo.find_active_groups()
    return [
        GroupItem(id=g.id, name=f"{datetime.now().year - g.year + 1}{g.specialty.short_name}{g.group_number}")
        for g in groups
    ]


@app.get(
    '/streak', 
    response_model=StreakItem, 
    tags=["study"],
    dependencies=[Depends(bearer_docs)], 
    summary="Стрик пользователя",
    description="Возвращает текущую и максимальную серию дней выполнения заданий. Обновляется автоматически при успешной оценке задания."
)
async def get_streak(
    student: StudentUser,
    use_case: GetStreak = Depends(container.get_user_streak)
):
    user_id = student["user_id"]
    result: GetStreakResponse = await use_case.execute(user_id)

    return StreakItem(
        current_streak=result.current_streak,
        longest_streak=result.longest_streak
    )


@app.post(
    "/task", 
    response_model=TaskResponse, 
    tags=["chat"],
    dependencies=[Depends(bearer_docs)], 
    summary="Начать практическую сессию",
    description="Ментор генерирует НОВОЕ задание при каждом вызове. Задание подбирается под самый слабый навык студента.",
    responses={
        401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"},
        500: {"model": ErrorResponse, "description": "Внутренняя ошибка или недоступность AI"},
        503: {"model": ErrorResponse, "description": "Нет доступных навыков для генерации задания"}
    }
)
async def start_task(
    student: StudentUser,
    task_case: StartSkillSession = Depends(container.get_start_skill_session),
):
    user_id = student["user_id"]
    result = await task_case.execute(user_id)
    return result


@app.get(
    "/task/current", 
    response_model=TaskResponse | None, 
    tags=["chat"],
    dependencies=[Depends(bearer_docs)], 
    summary="Текущее активное задание",
    description="Возвращает последнее выданное задание, если оно есть. Если активного задания нет, возвращает null. Используется для восстановления состояния после перезагрузки страницы.",
    responses={401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"}}
)
async def get_current_task(
    student: StudentUser,
    dialog_repo: DialogRepository = Depends(container.get_dialog_repo)
):
    user_id = student["user_id"]
    last_dialog = await dialog_repo.get_last_task_dialog(user_id=user_id)

    if not last_dialog or not last_dialog.ai_response:
        return None

    return TaskResponse(
        question=last_dialog.ai_response,
        question_id=last_dialog.question_id
    )


@app.post(
    "/chat", 
    response_model=ChatResponse, 
    tags=["chat"], 
    dependencies=[Depends(bearer_docs), Depends(require_role("student"))] 
)
async def chat(
    student: StudentUser,
    data: ChatRequest,
    use_case: ProcessChatMessage = Depends(container.get_process_chat_message) 
):
    request_data = ChatRequestData(message=data.message, question_id=data.question_id)
    result = await use_case.execute(user_id=student["user_id"], data=request_data)
    
    return ChatResponse(
        message=result.message,
        question_id=result.question_id,
        assessment=result.assessment,
        task_completed=result.task_completed
    )


@app.get(
    "/chat/history", 
    response_model=ChatHistoryResponse, 
    tags=["chat"], 
    dependencies=[Depends(bearer_docs), Depends(require_role("student"))] 
)
async def get_chat_history(
    student: StudentUser,
    limit: int = Query(50, ge=1, le=200),
    use_case: GetChatHistory = Depends(container.get_chat_history) 
):
    result = await use_case.execute(user_id=student["user_id"], username=student["username"], limit=limit)
    return result