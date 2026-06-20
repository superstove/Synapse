"""Shared request/response shapes. Kept thin — only what the routes consume."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineNode(BaseModel):
    id: str
    type: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    # React Flow nodes carry position/draggable/etc.; we accept-and-ignore the rest.
    model_config = {"extra": "allow"}


class PipelineEdge(BaseModel):
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    model_config = {"extra": "allow"}


class PipelinePayload(BaseModel):
    nodes: List[PipelineNode] = Field(default_factory=list)
    edges: List[PipelineEdge] = Field(default_factory=list)


class SavedPipelineCreate(BaseModel):
    name: str
    payload: PipelinePayload


class SavedPipelineOut(BaseModel):
    id: int
    name: str
    payload: PipelinePayload
    created_at: str
