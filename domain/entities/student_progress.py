from dataclasses import dataclass
from domain.entities.skill_matrix import SkillMatrix
from typing import Optional

@dataclass
class StudentProgress:
    id: Optional[int] = None
    student_id: int = None
    skill_id: int = None
    level: int = None
    weaknesses: str = None
    learn_order: int = None

    def is_mastered(self) -> bool:
        return (self.level or 0) >= 100

    