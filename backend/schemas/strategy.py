"""Strategy request bodies; service validation supplies the contract errors."""
from typing import Any

from pydantic import BaseModel


class StrategyUpdate(BaseModel):
    objectives: Any = None
    desired_outcomes: Any = None
    risks: Any = None
    plays: Any = None
    discovery_gaps: Any = None
    expected_version: Any = None


class StrategyLinksUpdate(BaseModel):
    task_ids: Any = None
    contact_ids: Any = None
    note_ids: Any = None


class SnapshotPublish(BaseModel):
    note: Any = None


class SnapshotRestore(BaseModel):
    expected_version: Any = None
