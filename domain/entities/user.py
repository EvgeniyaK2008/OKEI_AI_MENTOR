from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from domain.entities.study import Groups
from typing import Optional, Any


@dataclass
class UserRole(Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"

@dataclass
class User:
    id: Optional[int] = None
    username: str = None  
    hashed_password: str = None  
    first_name: str = None
    middle_name: str = None
    last_name: str = None
    role: UserRole = field(default_factory=lambda: UserRole.STUDENT)
    group: Any = None
    current_streak: int = 0
    longest_streak: int = 0
    last_activity_date: date | None = None

    def get_group(self):
        return self.group

    def get_course(self): 
        return self.group.get_course()

    def get_specialty_id(self):
        return self.group.get_specialty_id()



