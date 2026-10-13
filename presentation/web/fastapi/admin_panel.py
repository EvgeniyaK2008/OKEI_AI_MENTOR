from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from application.repositories.user_repository import UserRepository
from application.services.auth import verify_password
from config.config import Config
from domain.entities.user import User, UserRole
from infrastructure.database.models import *
from fastapi import FastAPI
from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware
from infrastructure.database.connection import sync_engine, async_session_factory
from infrastructure.repositories.postgres_user_repository import AsyncPostgresUserRepository

class UserAdmin(ModelView, model=UserModel):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"
    column_list = [
        UserModel.id,
        UserModel.username,
        UserModel.first_name,
        UserModel.last_name,
        UserModel.role,
        UserModel.group,
        UserModel.current_streak,
        UserModel.longest_streak,
        UserModel.last_activity_date,
    ]
    column_searchable_list = [UserModel.username, UserModel.first_name, UserModel.last_name]
    column_sortable_list = [UserModel.id, UserModel.current_streak, UserModel.longest_streak]

class GroupAdmin(ModelView, model=GroupModel):
    name = "Группа"
    name_plural = "Группы"
    icon = "fa-solid fa-users"
    column_list = [
        GroupModel.id,
        GroupModel.year,
        GroupModel.group_number,
        GroupModel.specialty,
        GroupModel.is_active,
    ]
    column_searchable_list = [GroupModel.group_number]


class SpecialtyAdmin(ModelView, model=SpecialtyModel):
    name = "Специальность"
    name_plural = "Специальности"
    icon = "fa-solid fa-graduation-cap"
    column_list = [
        SpecialtyModel.id,
        SpecialtyModel.code,
        SpecialtyModel.short_name,
        SpecialtyModel.full_name,
    ]
    column_searchable_list = [SpecialtyModel.code, SpecialtyModel.short_name]


class DialogAdmin(ModelView, model=DialogModel):
    name = "Диалог"
    name_plural = "Диалоги"
    icon = "fa-solid fa-comments"
    column_list = [
        DialogModel.id,
        DialogModel.user,
        DialogModel.question_id,
        DialogModel.user_message_time,
        DialogModel.ai_response_time,
    ]
    column_searchable_list = [DialogModel.user_message, DialogModel.question_id]
    column_sortable_list = [DialogModel.id, DialogModel.user_message_time]


class StudentProgressAdmin(ModelView, model=StudentProgressModel):
    name = "Прогресс"
    name_plural = "Прогресс студентов"
    icon = "fa-solid fa-chart-line"
    column_list = [
        StudentProgressModel.id,
        StudentProgressModel.student,
        StudentProgressModel.skill,
        StudentProgressModel.level,
        StudentProgressModel.weaknesses,
    ]
    column_searchable_list = [StudentProgressModel.weaknesses]
    column_sortable_list = [StudentProgressModel.level, StudentProgressModel.student_id]


class SkillMatrixAdmin(ModelView, model=SkillMatrixModel):
    name = "Навык"
    name_plural = "Матрица навыков"
    icon = "fa-solid fa-brain"
    column_list = [
        SkillMatrixModel.id,
        SkillMatrixModel.skill,
        SkillMatrixModel.course,
        SkillMatrixModel.specialty,
        SkillMatrixModel.criterions,
    ]
    column_searchable_list = [SkillMatrixModel.skill]



class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request):
        form = await request.form()
        
        username = form.get("username")
        password = form.get("password")

        if not username or not password:
            return False

        from infrastructure.database.connection import async_session_factory
        
        async with async_session_factory() as session:
            user_repo = AsyncPostgresUserRepository(session=session)
            user = await user_repo.find_by_username(username)

            if not user or user.role != UserRole.ADMIN or not verify_password(password, user.hashed_password):
                return False

        request.session.update({"authenticated": True})
        return True
    
    async def logout(self, request: Request):
        request.session.clear()
        return True

    async def authenticate(self, request: Request):
        return request.session.get("authenticated", False)

def setup_admin(app: FastAPI) -> Admin:
    config = Config.load()
    
    app.add_middleware(SessionMiddleware, secret_key=config.key)
    
    admin = Admin(
        app,
        sync_engine,
        title="AI Mentor Admin",
        authentication_backend=AdminAuth(secret_key=config.key)
    )
    
    admin.add_view(UserAdmin)
    admin.add_view(GroupAdmin)
    admin.add_view(SpecialtyAdmin)
    admin.add_view(DialogAdmin)
    admin.add_view(StudentProgressAdmin)
    admin.add_view(SkillMatrixAdmin)
    
    return admin