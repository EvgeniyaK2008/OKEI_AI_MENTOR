# main.py
import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import FastAPI, Request, Depends, Query, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field

from config.config import Config

from application.services.user_service import UserService
from application.services.dialog_service import DialogService
from application.services.auth import hash_password, verify_password, create_access_token, get_current_user, require_role

from application.interactors.start_skill_session import StartSkillSession
from application.interactors.get_chat_response import GetChatResponseWithContext, UserMessage, GetChatResponseWithContextResponse
from application.interactors.evaluate_student_answer import EvaluateStudentAnswer
from application.interactors.detect_student_answer import DetectStudentsAnswer, DetectStudentsAnswerResponse

from application.interactors.get_streak import GetStreak, GetStreakResponse
from application.interactors.get_admin_stats import GetAdminStats
from infrastructure.repositories.postgres_group_repository import AsyncPostgresGroupRepository
from presentation.web.fastapi.admin_panel import *

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
from infrastructure.dependency_fabrics import get_container
from presentation.web.fastapi.models import *


# ============================ Приложение ============================

CurrentUser = Annotated[dict, Depends(get_current_user)]
StudentUser = Annotated[dict, Depends(require_role("student"))]
ManagerUser = Annotated[dict, Depends(require_role("manager"))]

 
config = Config.load()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

bearer_docs = HTTPBearer(auto_error=False)
container = get_container()

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

# ============================ Роуты ============================

@app.get(
    "/manager/stats",
    response_model=AdminStatsResponse,
    tags=["stats"],
    dependencies=[Depends(require_role("manager"))],
    summary="Статистика для администратора",
    description="Полная статистика по студентам, группам, навыкам и активности за указанный период.",
)
async def get_admin_stats_endpoint(
    days: int = Query(30, ge=1, le=365, description="Период для daily_activity в днях"),
    use_case: GetAdminStats = Depends(container.get_admin_stats),
):
    result = await use_case.execute(days=days)
    return result

# исправить
@app.get('/me', response_model=UserPublic, tags=["auth"], dependencies=[Depends(bearer_docs)],
         summary="Текущий пользователь", 
         description="Возвращает профиль текущего пользователя по JWT-токену: ID, логин, ФИО, группа, роль и стрик.")
async def get_me(
    current_user: CurrentUser,
    user_repo: UserRepository = Depends(container.get_user_repo),
    group_repo: GroupRepository = Depends(container.get_group_repo),
    specialty_repo: SpecialtyRepository = Depends(container.get_specialty_repo),
):
    user_id = current_user["user_id"]
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


# исправить
@app.post("/login", response_model=LoginResponse, tags=["auth"],
          summary="Вход и получение токена",
          description="Проверяет логин/пароль и выдаёт JWT вместе с профилем пользователя.",
          responses={
              401: {"model": ErrorResponse, "description": "Неверный логин или пароль"},
              422: {"model": ErrorResponse, "description": "Ошибка валидации данных"}
          })
async def login_page(
    data: LoginRequest,
    user_repo: UserRepository = Depends(container.get_user_repo),
    group_repo: GroupRepository = Depends(container.get_group_repo),
    specialty_repo: SpecialtyRepository = Depends(container.get_specialty_repo),
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

# исправить
@app.post("/register", response_model=RegisterResponse, status_code=201, tags=["auth"],
          summary="Регистрация пользователя",
          description="Создаёт нового пользователя. Роль назначается через параметр (по умолчанию student). Ошибка 409 — логин уже занят.",
          responses={
              409: {"model": ErrorResponse, "description": "Username уже занят"},
              422: {"model": ErrorResponse, "description": "Ошибка валидации данных"}
          })
async def register(
    data: RegisterRequest,
    service: UserService = Depends(container.get_user_service),
    user_repo: UserRepository = Depends(container.get_user_repo),
    group_repo: GroupRepository = Depends(container.get_group_repo),
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
        group=group, role=UserRole.STUDENT,
    )
    return RegisterResponse(user_id=user.id, username=user.username)


@app.get("/skills", response_model=list[SkillItem], tags=["study"], 
         summary="Каталог навыков",
         description="Возвращает все навыки матрицы компетенций для курса и специальности текущего студента.")
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


@app.get("/progress", response_model=list[ProgressItem], tags=["study"], 
         dependencies=[Depends(bearer_docs), Depends(require_role("student"))],
         summary="Прогресс студента",
         description="Возвращает проценты освоения навыков (0–100) и слабые места по каждому навыку. Обновляется после оценки задания.")
async def get_progress(
    student: StudentUser,
    student_progress_repo: StudentProgressRepository = Depends(container.get_student_progress_repo),
    matrix_repo: SkillMatrixRepository = Depends(container.get_matrix_repo),
):
    user_id = StudentUser["user_id"]
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
async def get_groups(group_repo: AsyncPostgresGroupRepository = Depends(container.get_group_repo)):
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
    use_case: GetStreak = Depends(container.get_user_streak)
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
    student: StudentUser,
    task_case: StartSkillSession = Depends(container.get_start_skill_session),
):
    user_id = StudentUser["user_id"]
    result = await task_case.execute(user_id)
    return result


@app.get("/task/current", response_model=TaskResponse | None, tags=["chat"], 
         summary="Текущее активное задание",
         description="Возвращает последнее выданное задание, если оно есть. Если активного задания нет, возвращает null. Используется для восстановления состояния после перезагрузки страницы.",
         responses={401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"}})
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


@app.post("/chat", response_model=ChatResponse, tags=["chat"], 
          summary="Сообщение ментору",
          description="Единственный диалог студента с ментором. Если передан question_id, сообщение считается ответом на задание и запускает ИИ-детектор. Если детектор распознаёт ответ, запускается оценка (прогресс и стрик обновляются автоматически). Если assessment не null — задание считается выполненным, фронтенд должен сбросить активный question_id.",
          responses={
              401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"},
              422: {"model": ErrorResponse, "description": "Ошибка валидации (например, слишком длинное сообщение)"},
              500: {"model": ErrorResponse, "description": "Ошибка AI или БД"}
          })
async def chat(
    student: StudentUser,
    data: ChatRequest,
    dialog_service: DialogService = Depends(container.get_dialog_service),
    ai_service: AIService = Depends(container.get_ai_mentor),
    detection_case: DetectStudentsAnswer = Depends(container.get_detect_students_answer),
    evaluate_case: EvaluateStudentAnswer = Depends(container.get_evaluate_student_answer)
):
    user_id: int = student["user_id"]
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
         summary="История диалога",
         description="Возвращает последние N сообщений, отсортированных хронологически (старые сверху, новые снизу). Параметр limit ограничивает количество возвращаемых сообщений (по умолчанию 50, максимум 200).",
         responses={
             401: {"model": ErrorResponse, "description": "Нет токена или неверная роль"},
             422: {"model": ErrorResponse, "description": "Ошибка валидации параметра limit"}
         })
async def get_chat_history(
    student: StudentUser,
    limit: int = Query(50, ge=1, le=200, description="Сколько сообщений вернуть"),
    dialog_service: DialogService = Depends(container.get_dialog_service),
):
    user_id = student["user_id"]

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

    return ChatHistoryResponse(user_id=user_id, username=student["username"], messages=messages)
