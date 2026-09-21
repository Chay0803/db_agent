from pydantic import BaseModel
from typing import Optional, Any


class StudentCreate(BaseModel):
    name: str
    age: int
    department: str
    gpa: float
    email: str
    enrollment_year: int
    status: str = "active"


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    department: Optional[str] = None
    gpa: Optional[float] = None
    email: Optional[str] = None
    enrollment_year: Optional[int] = None
    status: Optional[str] = None


class StudentResponse(BaseModel):
    id: int
    name: str
    age: int
    department: str
    gpa: float
    email: str
    enrollment_year: int
    status: str

    class Config:
        from_attributes = True


class CourseResponse(BaseModel):
    id: int
    name: str
    department: str
    credits: int

    class Config:
        from_attributes = True


class EnrollmentResponse(BaseModel):
    id: int
    student_id: int
    course_id: int
    grade: str
    semester: str

    class Config:
        from_attributes = True


class AgentRequest(BaseModel):
    message: str


class AgentResponse(BaseModel):
    response: str
    db_action: Optional[Any] = None
