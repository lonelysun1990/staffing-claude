from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class ConfigORM(Base):
    __tablename__ = "config"

    id = Column(Integer, primary_key=True, default=1)
    granularity_weeks = Column(Integer, nullable=False, default=1)
    horizon_weeks = Column(Integer, nullable=False, default=26)


class DataScientistORM(Base):
    __tablename__ = "data_scientists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    level = Column(String, nullable=False)
    max_concurrent_projects = Column(Integer, nullable=False, default=1)
    efficiency = Column(Float, nullable=False, default=1.0)
    notes = Column(Text, nullable=True)

    assignments = relationship(
        "AssignmentORM", back_populates="data_scientist", cascade="all, delete-orphan"
    )
    skills = relationship(
        "DataScientistSkillORM", back_populates="data_scientist", cascade="all, delete-orphan"
    )


class ProjectORM(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    fte_requirements = relationship(
        "ProjectWeekORM", back_populates="project", cascade="all, delete-orphan"
    )
    assignments = relationship(
        "AssignmentORM", back_populates="project", cascade="all, delete-orphan"
    )
    required_skills = relationship(
        "ProjectSkillORM", back_populates="project", cascade="all, delete-orphan"
    )


class ProjectWeekORM(Base):
    __tablename__ = "project_weeks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    week_start = Column(Date, nullable=False)
    fte = Column(Float, nullable=False)

    project = relationship("ProjectORM", back_populates="fte_requirements")


class AssignmentORM(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_scientist_id = Column(Integer, ForeignKey("data_scientists.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    week_start = Column(Date, nullable=False)
    allocation = Column(Float, nullable=False)

    data_scientist = relationship("DataScientistORM", back_populates="assignments")
    project = relationship("ProjectORM", back_populates="assignments")
    audit_logs = relationship("AuditLogORM", back_populates="assignment", cascade="all, delete-orphan")


class DataScientistSkillORM(Base):
    __tablename__ = "data_scientist_skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_scientist_id = Column(Integer, ForeignKey("data_scientists.id"), nullable=False)
    skill = Column(String, nullable=False)

    __table_args__ = (UniqueConstraint("data_scientist_id", "skill"),)

    data_scientist = relationship("DataScientistORM", back_populates="skills")


class ProjectSkillORM(Base):
    __tablename__ = "project_skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    skill = Column(String, nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "skill"),)

    project = relationship("ProjectORM", back_populates="required_skills")


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=True)
    action = Column(String, nullable=False)  # "created", "updated", "deleted"
    changed_by = Column(String, nullable=True)
    changed_at = Column(String, nullable=False)  # ISO datetime string
    details = Column(Text, nullable=True)  # JSON string of what changed

    assignment = relationship("AssignmentORM", back_populates="audit_logs")
