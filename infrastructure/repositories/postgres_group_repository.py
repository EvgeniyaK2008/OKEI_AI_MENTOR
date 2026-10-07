import logging
from typing import List, Optional
from sqlalchemy import select, update, delete, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from application.repositories.group_repository import GroupRepository
from domain.entities.study import Groups, Specialty  
from infrastructure.database.models import GroupModel, UserModel

logger = logging.getLogger(__name__)

class AsyncPostgresGroupRepository(GroupRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, group: Groups) -> Groups:
        try:
            spec_id = group.specialty.id if group.specialty else None
            
            if group.id:
                stmt = (
                    update(GroupModel)
                    .where(GroupModel.id == group.id)
                    .values(
                        year=group.year,
                        specialty_id=spec_id,
                        group_number=group.group_number,
                        is_active=group.is_active
                    )
                )
                await self.session.execute(stmt)
            else:
                db_group = GroupModel(
                    year=group.year,
                    specialty_id=spec_id,
                    group_number=group.group_number,
                    is_active=group.is_active
                )
                self.session.add(db_group)
                await self.session.flush()
                group.id = db_group.id

            await self.session.commit()
            logger.info(f"Group {group.id} saved successfully")
            return group
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Couldn't save group: {e}")
            raise

    async def find_by_id(self, group_id: int) -> Optional[Groups]:
        result = await self.session.execute(
            select(GroupModel)
            .options(joinedload(GroupModel.specialty))  
            .where(GroupModel.id == group_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        
        specialty = None
        if row.specialty:
            specialty = Specialty(
                id=row.specialty.id,
                code=row.specialty.code,
                short_name=row.specialty.short_name,
                full_name=row.specialty.full_name,
            )
        
        return Groups(
            id=row.id,
            year=row.year,
            specialty=specialty,
            group_number=row.group_number,
            is_active=row.is_active
        )

    async def find_by_specialty(self, specialty_id: int) -> List[Groups]:
        result = await self.session.execute(
            select(GroupModel)
            .options(joinedload(GroupModel.specialty)) 
            .where(GroupModel.specialty_id == specialty_id)
            .order_by(desc(GroupModel.year))
        )
        
        groups = []
        for r in result.scalars().all():
            specialty = None
            if r.specialty:
                specialty = Specialty(
                    id=r.specialty.id,
                    code=r.specialty.code,
                    short_name=r.specialty.short_name,
                    full_name=r.specialty.full_name,
                )
            groups.append(Groups(
                id=r.id, 
                year=r.year, 
                specialty=specialty,
                group_number=r.group_number, 
                is_active=r.is_active
            ))
        return groups

    async def find_active_groups(self) -> List[Groups]:
        result = await self.session.execute(
            select(GroupModel)
            .where(GroupModel.is_active == True)
            .options(joinedload(GroupModel.specialty))
            .order_by(desc(GroupModel.year))
        )
        
        groups = []
        for r in result.scalars().all():
            specialty = None
            if r.specialty:
                specialty = Specialty(
                    id=r.specialty.id,
                    code=r.specialty.code,
                    short_name=r.specialty.short_name,
                    full_name=r.specialty.full_name,
                )
            groups.append(Groups(
                id=r.id, 
                year=r.year, 
                specialty=specialty,
                group_number=r.group_number, 
                is_active=r.is_active
            ))
        return groups

    async def find_by_year(self, year: int) -> List[Groups]:
        result = await self.session.execute(
            select(GroupModel)
            .options(joinedload(GroupModel.specialty))  
            .where(GroupModel.year == year)
            .order_by(desc(GroupModel.year))
        )
        
        groups = []
        for r in result.scalars().all():
            specialty = None
            if r.specialty:
                specialty = Specialty(
                    id=r.specialty.id,
                    code=r.specialty.code,
                    short_name=r.specialty.short_name,
                    full_name=r.specialty.full_name,
                )
            groups.append(Groups(
                id=r.id, 
                year=r.year, 
                specialty=specialty,
                group_number=r.group_number, 
                is_active=r.is_active
            ))
        return groups

    async def delete(self, group_id: int) -> bool:
        try:
            count_res = await self.session.execute(
                select(func.count()).select_from(UserModel).where(UserModel.group_id == group_id)
            )
            if count_res.scalar() > 0:
                return False
            
            res = await self.session.execute(
                delete(GroupModel).where(GroupModel.id == group_id)
            )
            await self.session.commit()
            return res.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Couldn't delete group {group_id}: {e}")
            raise