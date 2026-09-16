from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Any


@dataclass
class Department:
    id: Optional[int] = None
    name: str = None


@dataclass
class Specialty:
    id: Optional[int] = None
    code: str = None
    short_name: str = None
    full_name: str = None
    department: Any = None


@dataclass
class Groups:
    id: Optional[int] = None
    year: int = None
    specialty: Any = None
    group_number: int = None
    is_active: bool = False
    

    def get_specialty_id(self) -> int:
        return self.specialty.id
    
    def get_course(self) -> int:
        now = datetime.now()
        academic_year_start = now.year if now.month >= 9 else now.year - 1
        return academic_year_start - self.year + 1