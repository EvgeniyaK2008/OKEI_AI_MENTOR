from pydantic import BaseModel
from application.repositories.user_repository import UserRepository
from application.repositories.group_repository import GroupRepository
from application.services.auth import hash_password
from domain.entities.user import UserRole

class RegisterRequestData(BaseModel):
    username: str
    password: str
    group_id: int | None
    first_name: str
    middle_name: str
    last_name: str

class RegisterResponseData(BaseModel):
    user_id: int
    username: str

class RegisterUser:
    def __init__(self, user_repo: UserRepository, group_repo: GroupRepository):
        self.user_repo = user_repo
        self.group_repo = group_repo

    async def execute(self, data: RegisterRequestData) -> RegisterResponseData:
        existing = await self.user_repo.find_by_username(data.username)
        if existing:
            raise ValueError("Username already exists")

        group = None
        if data.group_id:
            group = await self.group_repo.find_by_id(data.group_id)

        new_user = await self.user_repo.save( 
            username=data.username,
            hashed_password=hash_password(data.password),
            first_name=data.first_name,
            middle_name=data.middle_name,
            last_name=data.last_name,
            group=group,
            role=UserRole.STUDENT
        )
        
        return RegisterResponseData(user_id=new_user.id, username=new_user.username)