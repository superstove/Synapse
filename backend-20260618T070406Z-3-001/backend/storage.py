"""SQLite-backed pipeline persistence.

Pipelines are stored as a name + the raw JSON payload. We don't try to
normalize nodes/edges into relational tables — the frontend is the source
of truth for shape, and JSON storage lets the schema evolve without
migrations. A real production version would probably store nodes/edges
relationally to enable queries like "all pipelines using an LLM node",
but that's out of scope.
"""

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from models import PipelinePayload, SavedPipelineCreate, SavedPipelineOut

DATABASE_URL = "sqlite:///./pipelines.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class SavedPipeline(Base):
    __tablename__ = "pipelines"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def _to_out(row: SavedPipeline) -> SavedPipelineOut:
    return SavedPipelineOut(
        id=row.id,
        name=row.name,
        payload=PipelinePayload.model_validate(json.loads(row.payload_json)),
        created_at=row.created_at.isoformat(),
    )


def create_pipeline(payload: SavedPipelineCreate) -> SavedPipelineOut:
    with SessionLocal() as session:  # type: Session
        row = SavedPipeline(
            name=payload.name,
            payload_json=payload.payload.model_dump_json(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_out(row)


def list_pipelines() -> List[SavedPipelineOut]:
    with SessionLocal() as session:
        rows = session.query(SavedPipeline).order_by(SavedPipeline.created_at.desc()).all()
        return [_to_out(row) for row in rows]


def get_pipeline(pipeline_id: int) -> Optional[SavedPipelineOut]:
    with SessionLocal() as session:
        row = session.get(SavedPipeline, pipeline_id)
        return _to_out(row) if row else None


def delete_pipeline(pipeline_id: int) -> bool:
    with SessionLocal() as session:
        row = session.get(SavedPipeline, pipeline_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True
