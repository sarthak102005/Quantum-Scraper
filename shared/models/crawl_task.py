"""
shared/models/crawl_task.py

CrawlTask — the top-level input model representing a scraping job.
Created by the ADK Planner from the user's natural-language prompt.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TraversalStrategy(str, Enum):
    BFS = "bfs"
    DFS = "dfs"


class CrawlTask(BaseModel):
    """Represents a single scraping job issued by the ADK Planner."""

    schema_version: str = Field(default="1.0", frozen=True)

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    seed_url: str
    domain: str
    max_pages: int = Field(default=100, ge=1)
    max_depth: int = Field(default=3, ge=1)
    target_page_types: list[Literal["product", "category", "unknown"]] = Field(
        default_factory=lambda: ["product"]
    )
    traversal_strategy: TraversalStrategy = TraversalStrategy.BFS
    resume_from_checkpoint: bool = False
    checkpoint_path: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, object] = Field(default_factory=dict)
