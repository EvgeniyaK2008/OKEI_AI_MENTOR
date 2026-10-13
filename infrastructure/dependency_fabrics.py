from functools import lru_cache

from fastapi import Depends

from application.interactors.authenticate_user import AuthenticateUser
from application.interactors.detect_student_answer import DetectStudentsAnswer
from application.interactors.evaluate_student_answer import EvaluateStudentAnswer
from application.interactors.get_admin_stats import GetAdminStats
from application.interactors.get_chat_history import GetChatHistory
from application.interactors.get_skill_for_student import GetSkillForStudent
from application.interactors.get_streak import GetStreak
from application.interactors.get_user_info import GetUserProfile
from application.interactors.process_chat_message import ProcessChatMessage
from application.interactors.register_user import RegisterUser
from application.interactors.start_skill_session import StartSkillSession
from application.ports.ai.ai_port import AIService
from application.repositories.dialog_repository import DialogRepository
from application.repositories.group_repository import GroupRepository
from application.repositories.skill_matrix_repository import SkillMatrixRepository
from application.repositories.specialty_repository import SpecialtyRepository
from application.repositories.stats_repository import StatsRepository
from application.repositories.student_progress_repository import StudentProgressRepository
from application.repositories.user_repository import UserRepository
from application.services.dialog_service import DialogService
from application.services.user_service import UserService
from config.config import Config
from infrastructure.database.connection import get_db
from infrastructure.repositories.postgres_stats_repository import AsyncPostgresStatsRepository
from infrastructure.repositories.postgres_user_repository import AsyncPostgresUserRepository
from infrastructure.repositories.postgres_skill_matrix_repository import AsyncPostgresSkillMatrixRepository
from infrastructure.repositories.postgres_student_progress_repository import AsyncPostgresStudentProgressRepository
from infrastructure.repositories.postgres_group_repository import AsyncPostgresGroupRepository
from infrastructure.repositories.postgres_dialog_repository import AsyncPostgresDialogRepository
from infrastructure.repositories.postgres_specialty_repository import AsyncPostgresSpecialtyRepository

from infrastructure.ai.yandex_ai_service import YandexAIMainModelService
from sqlalchemy.ext.asyncio import AsyncSession


class Container:
    def __init__(self, config: Config):
        self._config = config
        self.mentor_ai = YandexAIMainModelService(self._config.mentor_ai)
        self.secondary_ai = YandexAIMainModelService(self._config.secondary_ai)

    # --- Базовые репозитории ---
    async def get_user_repo(self, db: AsyncSession = Depends(get_db)) -> UserRepository:
        return AsyncPostgresUserRepository(db)

    async def get_group_repo(self, db: AsyncSession = Depends(get_db)) -> GroupRepository:
        return AsyncPostgresGroupRepository(db)

    async def get_specialty_repo(self, db: AsyncSession = Depends(get_db)) -> SpecialtyRepository:
        return AsyncPostgresSpecialtyRepository(db)

    async def get_student_progress_repo(self, db: AsyncSession = Depends(get_db)) -> StudentProgressRepository:
        return AsyncPostgresStudentProgressRepository(db)

    async def get_matrix_repo(self, db: AsyncSession = Depends(get_db)) -> SkillMatrixRepository:
        return AsyncPostgresSkillMatrixRepository(db)

    async def get_dialog_repo(self, db: AsyncSession = Depends(get_db)) -> DialogRepository:
        return AsyncPostgresDialogRepository(db)

    async def get_stats_repo(self, db: AsyncSession = Depends(get_db)) -> StatsRepository:
        return AsyncPostgresStatsRepository(db)

    # --- Сервисы ---
    async def get_dialog_service(self, db: AsyncSession = Depends(get_db)) -> DialogService:
        return DialogService(AsyncPostgresDialogRepository(db))

    async def get_user_service(self, db: AsyncSession = Depends(get_db)) -> UserService:
        return UserService(
            AsyncPostgresUserRepository(db),
            AsyncPostgresSkillMatrixRepository(db),
            AsyncPostgresStudentProgressRepository(db)
        )

    async def get_ai_mentor(self, db: AsyncSession = Depends(get_db)) -> AIService:
        return YandexAIMainModelService(self._config.mentor_ai)

    async def get_ai_secondary(self, db: AsyncSession = Depends(get_db)) -> AIService:
        return YandexAIMainModelService(self._config.secondary_ai)

    # --- Интеракторы (Use Cases) ---
    # ИСПРАВЛЕНО: Больше нет Depends(метод_класса). Мы берем db и собираем граф вручную.
    
    async def get_admin_stats(self, db: AsyncSession = Depends(get_db)) -> GetAdminStats:
        return GetAdminStats(stats_repo=AsyncPostgresStatsRepository(db))

    async def get_get_skill_for_student(self, db: AsyncSession = Depends(get_db)) -> GetSkillForStudent:
        user_repo = AsyncPostgresUserRepository(db)
        return GetSkillForStudent(
            student_progress_repo=AsyncPostgresStudentProgressRepository(db),
            skill_matrix_repo=AsyncPostgresSkillMatrixRepository(db),
            user_repo=user_repo
        )

    async def get_start_skill_session(self, db: AsyncSession = Depends(get_db)) -> StartSkillSession:
        user_repo = AsyncPostgresUserRepository(db)
        dialog_repo = AsyncPostgresDialogRepository(db)
        
        return StartSkillSession(
            ai_service=YandexAIMainModelService(self._config.mentor_ai),
            dialog_service=DialogService(dialog_repo),
            user_repo=user_repo,
            get_skill_for_student=GetSkillForStudent(
                student_progress_repo=AsyncPostgresStudentProgressRepository(db),
                skill_matrix_repo=AsyncPostgresSkillMatrixRepository(db),
                user_repo=user_repo,
            ),
            student_progress_repo=AsyncPostgresStudentProgressRepository(db),
            specialty_repo=AsyncPostgresSpecialtyRepository(db),
            group_repo=AsyncPostgresGroupRepository(db)
        )

    async def get_evaluate_student_answer(self, db: AsyncSession = Depends(get_db)) -> EvaluateStudentAnswer:
        dialog_repo = AsyncPostgresDialogRepository(db)
        user_repo = AsyncPostgresUserRepository(db)

        return EvaluateStudentAnswer(
            dialog_service=DialogService(dialog_repo),
            student_progress_repo=AsyncPostgresStudentProgressRepository(db),
            get_skill_for_student=GetSkillForStudent(
                student_progress_repo=AsyncPostgresStudentProgressRepository(db),
                skill_matrix_repo=AsyncPostgresSkillMatrixRepository(db),
                user_repo=user_repo
            ),
            dialog_repo=dialog_repo,
            ai_service=YandexAIMainModelService(self._config.secondary_ai),
            user_repo=user_repo,
        )

    async def get_detect_students_answer(self, db: AsyncSession = Depends(get_db)) -> DetectStudentsAnswer:
        return DetectStudentsAnswer(
            ai_service=YandexAIMainModelService(self._config.secondary_ai),
            dialog_repo=AsyncPostgresDialogRepository(db)
        )

    async def get_user_streak(self, db: AsyncSession = Depends(get_db)) -> GetStreak:
        return GetStreak(user_repo=AsyncPostgresUserRepository(db))

    # ============================ НОВЫЕ ФАБРИКИ (ИСПРАВЛЕННЫЕ) ============================

    async def get_user_profile(self, db: AsyncSession = Depends(get_db)) -> GetUserProfile:
        return GetUserProfile(user_repo=AsyncPostgresUserRepository(db))

    async def get_authenticate_user(self, db: AsyncSession = Depends(get_db)) -> AuthenticateUser:
        user_repo = AsyncPostgresUserRepository(db)
        return AuthenticateUser(
            user_repo=user_repo,
            get_user_profile=GetUserProfile(user_repo=user_repo) # Переиспользуем тот же инстанс
        )

    async def get_register_user(self, db: AsyncSession = Depends(get_db)) -> RegisterUser:
        return RegisterUser(
            user_repo=AsyncPostgresUserRepository(db),
            group_repo=AsyncPostgresGroupRepository(db)
        )

    async def get_chat_history(self, db: AsyncSession = Depends(get_db)) -> GetChatHistory:
        return GetChatHistory(dialog_repo=AsyncPostgresDialogRepository(db))

    async def get_process_chat_message(self, db: AsyncSession = Depends(get_db)) -> ProcessChatMessage:
        dialog_repo = AsyncPostgresDialogRepository(db)
        user_repo = AsyncPostgresUserRepository(db)
        
        return ProcessChatMessage(
            dialog_service=DialogService(dialog_repo),
            ai_service=YandexAIMainModelService(self._config.mentor_ai),
            detect_case=DetectStudentsAnswer(
                ai_service=YandexAIMainModelService(self._config.secondary_ai),
                dialog_repo=dialog_repo
            ),
            evaluate_case=EvaluateStudentAnswer(
                dialog_service=DialogService(dialog_repo),
                student_progress_repo=AsyncPostgresStudentProgressRepository(db),
                get_skill_for_student=GetSkillForStudent(
                    student_progress_repo=AsyncPostgresStudentProgressRepository(db),
                    skill_matrix_repo=AsyncPostgresSkillMatrixRepository(db),
                    user_repo=user_repo
                ),
                dialog_repo=dialog_repo,
                ai_service=YandexAIMainModelService(self._config.secondary_ai),
                user_repo=user_repo,
            )
        )

@lru_cache
def get_container() -> Container:
    return Container(Config.load())