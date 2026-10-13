from pydantic import BaseModel, Field, validator
from typing import Literal, Optional, List
from datetime import datetime

from application.interactors.evaluate_student_answer import EvaluateStudentAnswerResponse


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
