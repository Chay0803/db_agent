from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship

from .database import Base


class Student(Base):
    __tablename__ = "students"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, nullable=False)
    age             = Column(Integer, nullable=False)
    department      = Column(String, nullable=False)
    gpa             = Column(Float, nullable=False)
    email           = Column(String, unique=True, nullable=False)
    enrollment_year = Column(Integer, nullable=False)
    status          = Column(String, default="active")  # active | probation | graduated

    enrollments = relationship("Enrollment", back_populates="student", cascade="all, delete")


class Course(Base):
    __tablename__ = "courses"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False)
    department = Column(String, nullable=False)
    credits    = Column(Integer, nullable=False)

    enrollments = relationship("Enrollment", back_populates="course")


class Enrollment(Base):
    __tablename__ = "enrollments"

    id         = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    course_id  = Column(Integer, ForeignKey("courses.id"), nullable=False)
    grade      = Column(String, nullable=False)
    semester   = Column(String, nullable=False)

    student = relationship("Student", back_populates="enrollments")
    course  = relationship("Course",  back_populates="enrollments")
