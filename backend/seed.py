from sqlalchemy.orm import Session
from models import Student, Course, Enrollment

STUDENTS = [
    {"name": "Aisha Patel",     "age": 21, "department": "Computer Science",       "gpa": 3.9, "email": "aisha.patel@uni.edu",     "enrollment_year": 2022, "status": "active"},
    {"name": "Rohan Mehta",     "age": 20, "department": "Electrical Engineering",  "gpa": 3.4, "email": "rohan.mehta@uni.edu",     "enrollment_year": 2023, "status": "active"},
    {"name": "Priya Sharma",    "age": 22, "department": "Computer Science",        "gpa": 3.6, "email": "priya.sharma@uni.edu",    "enrollment_year": 2021, "status": "active"},
    {"name": "Arjun Singh",     "age": 19, "department": "Mechanical Engineering",  "gpa": 2.8, "email": "arjun.singh@uni.edu",     "enrollment_year": 2024, "status": "active"},
    {"name": "Divya Nair",      "age": 23, "department": "Data Science",            "gpa": 3.7, "email": "divya.nair@uni.edu",      "enrollment_year": 2021, "status": "active"},
    {"name": "Vikram Rao",      "age": 20, "department": "Civil Engineering",       "gpa": 1.9, "email": "vikram.rao@uni.edu",      "enrollment_year": 2023, "status": "probation"},
    {"name": "Sneha Reddy",     "age": 21, "department": "Data Science",            "gpa": 3.2, "email": "sneha.reddy@uni.edu",     "enrollment_year": 2022, "status": "active"},
    {"name": "Kiran Bose",      "age": 22, "department": "Computer Science",        "gpa": 2.5, "email": "kiran.bose@uni.edu",      "enrollment_year": 2022, "status": "active"},
    {"name": "Meera Joshi",     "age": 20, "department": "Electrical Engineering",  "gpa": 3.8, "email": "meera.joshi@uni.edu",     "enrollment_year": 2023, "status": "active"},
    {"name": "Deepak Kumar",    "age": 24, "department": "Mechanical Engineering",  "gpa": 1.7, "email": "deepak.kumar@uni.edu",    "enrollment_year": 2020, "status": "probation"},
    {"name": "Ananya Verma",    "age": 21, "department": "Computer Science",        "gpa": 3.5, "email": "ananya.verma@uni.edu",    "enrollment_year": 2022, "status": "active"},
    {"name": "Siddharth Das",   "age": 23, "department": "Data Science",            "gpa": 4.0, "email": "sid.das@uni.edu",         "enrollment_year": 2021, "status": "active"},
    {"name": "Kavya Menon",     "age": 22, "department": "Civil Engineering",       "gpa": 3.1, "email": "kavya.menon@uni.edu",     "enrollment_year": 2022, "status": "active"},
    {"name": "Rahul Gupta",     "age": 25, "department": "Electrical Engineering",  "gpa": 2.3, "email": "rahul.gupta@uni.edu",     "enrollment_year": 2020, "status": "active"},
    {"name": "Ishaan Chopra",   "age": 20, "department": "Mechanical Engineering",  "gpa": 3.3, "email": "ishaan.chopra@uni.edu",   "enrollment_year": 2023, "status": "active"},
]

COURSES = [
    {"name": "Data Structures & Algorithms", "department": "Computer Science",      "credits": 4},
    {"name": "Machine Learning",             "department": "Data Science",           "credits": 3},
    {"name": "Circuit Design",               "department": "Electrical Engineering", "credits": 3},
    {"name": "Thermodynamics",               "department": "Mechanical Engineering", "credits": 3},
    {"name": "Database Systems",             "department": "Computer Science",       "credits": 4},
    {"name": "Structural Engineering",       "department": "Civil Engineering",      "credits": 3},
    {"name": "Operating Systems",            "department": "Computer Science",       "credits": 3},
    {"name": "Deep Learning",                "department": "Data Science",           "credits": 3},
    {"name": "Power Systems",                "department": "Electrical Engineering", "credits": 3},
    {"name": "Fluid Mechanics",              "department": "Mechanical Engineering", "credits": 3},
]

ENROLLMENTS = [
    (0,  0, "A",  "Fall 2024"),
    (0,  4, "A+", "Fall 2024"),
    (0,  6, "A-", "Spring 2024"),
    (1,  2, "B+", "Fall 2024"),
    (1,  8, "B",  "Spring 2024"),
    (2,  0, "A-", "Spring 2024"),
    (2,  4, "A",  "Fall 2024"),
    (3,  3, "C+", "Fall 2024"),
    (3,  9, "C",  "Spring 2024"),
    (4,  1, "A",  "Fall 2024"),
    (4,  7, "A+", "Spring 2024"),
    (5,  5, "D",  "Fall 2024"),
    (6,  1, "B",  "Fall 2024"),
    (6,  7, "B+", "Spring 2024"),
    (7,  0, "C+", "Fall 2024"),
    (8,  2, "A",  "Fall 2024"),
    (8,  8, "A-", "Spring 2024"),
    (9,  3, "D",  "Fall 2024"),
    (10, 0, "A-", "Fall 2024"),
    (11, 1, "A+", "Fall 2024"),
    (11, 7, "A+", "Spring 2024"),
    (12, 5, "B+", "Fall 2024"),
    (13, 2, "C",  "Fall 2024"),
    (14, 3, "B",  "Fall 2024"),
]


def seed_database(db: Session):
    if db.query(Student).count() > 0:
        return

    course_objs = []
    for c in COURSES:
        obj = Course(**c)
        db.add(obj)
        course_objs.append(obj)
    db.flush()

    student_objs = []
    for s in STUDENTS:
        obj = Student(**s)
        db.add(obj)
        student_objs.append(obj)
    db.flush()

    for s_idx, c_idx, grade, semester in ENROLLMENTS:
        db.add(Enrollment(
            student_id=student_objs[s_idx].id,
            course_id=course_objs[c_idx].id,
            grade=grade,
            semester=semester,
        ))

    db.commit()
    print("✅  Database seeded with dummy data.")
