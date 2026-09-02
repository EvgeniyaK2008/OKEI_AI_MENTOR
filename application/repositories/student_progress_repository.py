from abc import ABC, abstractmethod
from typing import List, Optional
from domain.entities.user import User
from domain.entities.student_progress import StudentProgress


class StudentProgressRepository(ABC):
    @abstractmethod
    async def find_by_id(self, user_id: int) -> User:
        pass

    @abstractmethod
    async def save(self, student_progress: StudentProgress):
        pass

    @abstractmethod
    async def find_by_student_and_skill(self, student_id: int, skill_id: int) -> Optional[StudentProgress]:
        pass

    @abstractmethod
    async def find_by_student_id(self, student_id: int) -> List[StudentProgress]:
        pass

    @abstractmethod
    async def upsert(self, progress: StudentProgress) -> StudentProgress:
        pass