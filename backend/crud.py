from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from .models import Student, Course, Enrollment
from .schemas import StudentCreate, StudentUpdate


# ── Students ──────────────────────────────────────────────────────────────────

def get_students(db: Session, department=None, min_gpa=None, max_gpa=None, status=None):
    q = db.query(Student)
    if department: q = q.filter(Student.department.ilike(f"%{department}%"))
    if min_gpa is not None: q = q.filter(Student.gpa >= min_gpa)
    if max_gpa is not None: q = q.filter(Student.gpa <= max_gpa)
    if status: q = q.filter(Student.status == status)
    return q.order_by(Student.id).all()


def get_student(db: Session, student_id: int):
    return db.query(Student).filter(Student.id == student_id).first()


def create_student(db: Session, data: StudentCreate):
    student = Student(**data.model_dump())
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def update_student(db: Session, student_id: int, data: StudentUpdate):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return None
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(student, field, value)
    db.commit()
    db.refresh(student)
    return student


def delete_student(db: Session, student_id: int):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return False
    db.delete(student)
    db.commit()
    return True


# ── Courses & Enrollments ─────────────────────────────────────────────────────

def get_courses(db: Session):
    return db.query(Course).all()


def update_course(db: Session, course_id: int, data: dict):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        return None
    for field, value in data.items():
        if hasattr(course, field):
            setattr(course, field, value)
    db.commit()
    db.refresh(course)
    return course


def find_and_update_course(db: Session, name_query: str, data: dict):
    courses = db.query(Course).all()
    matched = [c for c in courses if name_query.lower() in c.name.lower()]
    if not matched:
        return None, None
    target = matched[0]
    return update_course(db, target.id, data), target


def get_enrollments(db: Session, student_id: int):
    return db.query(Enrollment).filter(Enrollment.student_id == student_id).all()


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_summary_analytics(db: Session):
    students = db.query(Student).all()
    total = len(students)
    if total == 0:
        return {}
    avg_gpa    = round(sum(s.gpa for s in students) / total, 2)
    active     = sum(1 for s in students if s.status == "active")
    probation  = sum(1 for s in students if s.status == "probation")
    graduated  = sum(1 for s in students if s.status == "graduated")
    top_student = max(students, key=lambda s: s.gpa)
    return {
        "total_students": total,
        "average_gpa": avg_gpa,
        "active": active,
        "probation": probation,
        "graduated": graduated,
        "highest_gpa": top_student.gpa,
        "top_student": top_student.name,
    }


def get_department_analytics(db: Session):
    rows = (
        db.query(
            Student.department,
            func.count(Student.id).label("count"),
            func.round(func.avg(Student.gpa), 2).label("avg_gpa"),
            func.max(Student.gpa).label("max_gpa"),
            func.min(Student.gpa).label("min_gpa"),
        )
        .group_by(Student.department)
        .all()
    )
    return [
        {"department": r.department, "count": r.count,
         "avg_gpa": r.avg_gpa, "max_gpa": r.max_gpa, "min_gpa": r.min_gpa}
        for r in rows
    ]


def get_at_risk_students(db: Session):
    students = (
        db.query(Student)
        .filter((Student.gpa < 2.0) | (Student.status == "probation"))
        .all()
    )
    return [
        {"id": s.id, "name": s.name, "department": s.department,
         "gpa": s.gpa, "status": s.status,
         "risk_reason": "GPA below 2.0" if s.gpa < 2.0 else "Academic probation"}
        for s in students
    ]


def get_student_ranking(db: Session):
    students = db.query(Student).order_by(Student.gpa.desc()).all()
    return [
        {"rank": i + 1, "id": s.id, "name": s.name,
         "department": s.department, "gpa": s.gpa}
        for i, s in enumerate(students)
    ]


def get_student_report(db: Session, student_id: int):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return None
    enrollments = db.query(Enrollment).filter(Enrollment.student_id == student_id).all()
    enrollment_details = []
    for e in enrollments:
        course = db.query(Course).filter(Course.id == e.course_id).first()
        enrollment_details.append({
            "course": course.name if course else "Unknown",
            "department": course.department if course else "",
            "credits": course.credits if course else 0,
            "grade": e.grade,
            "semester": e.semester,
        })
    dept_avg = (
        db.query(func.avg(Student.gpa))
        .filter(Student.department == student.department)
        .scalar()
    )
    ranking = get_student_ranking(db)
    rank = next((r["rank"] for r in ranking if r["id"] == student_id), None)
    return {
        "student": {
            "id": student.id, "name": student.name, "age": student.age,
            "department": student.department, "gpa": student.gpa,
            "email": student.email, "enrollment_year": student.enrollment_year,
            "status": student.status,
        },
        "enrollments": enrollment_details,
        "analytics": {
            "department_avg_gpa": round(dept_avg, 2) if dept_avg else None,
            "overall_rank": rank,
            "total_credits": sum(e["credits"] for e in enrollment_details),
            "courses_enrolled": len(enrollment_details),
        },
    }