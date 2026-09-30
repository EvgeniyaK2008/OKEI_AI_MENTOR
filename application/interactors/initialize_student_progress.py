async def initialize_student_progress(self, user: User):
        """Business logic: determine which skills to initialize"""
        group = user.group
        
        skills = await self.skill_matrix_repository.find_by_course_and_specialty(
            course= int(datetime.now.year) - group.year,
            specialty_id=group.specialty.id
        )
        
        for skill in skills:
            existing = await self.student_progress_repository.find_by_student_and_skill(
                user.id, skill.id
            )
            
            if not existing:
                progress = StudentProgress(
                    student_id=user.id,
                    skill_id=skill.id,
                    level=0,
                    weaknesses=""
                )
  
                await self.student_progress_repository.save(progress)