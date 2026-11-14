from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, ValidationError

MAX_PROCESSED = 500


class ProcessedState(BaseModel):
    model_config = ConfigDict(frozen=True)

    processed_ids: list[str] = []
    last_uid: Optional[int] = None
    uid_validity: Optional[int] = None

    @classmethod
    def load(cls, path: Union[str, Path]) -> "ProcessedState":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return cls()
        try:
            return cls.model_validate_json(text)
        except ValidationError:
            return cls()

    def save(self, path: Union[str, Path]) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(), encoding="utf-8")

    def is_processed(self, message_id: str) -> bool:
        return message_id in self.processed_ids

    def mark_processed(self, message_id: str) -> "ProcessedState":
        if message_id in self.processed_ids:
            return self
        updated = [*self.processed_ids, message_id][-MAX_PROCESSED:]
        return self.model_copy(update={"processed_ids": updated})

    def has_baseline(self) -> bool:
        return self.last_uid is not None

    def with_baseline(self, last_uid: int, uid_validity: int) -> "ProcessedState":
        """Ustawia punkt startowy ('od teraz') – używane przy pierwszym starcie albo
        gdy serwer zmienił UIDVALIDITY (stare UID-y przestają być wiarygodne)."""
        return self.model_copy(update={"last_uid": last_uid, "uid_validity": uid_validity})

    def advance_uid(self, new_last_uid: int) -> "ProcessedState":
        current = self.last_uid or 0
        if new_last_uid <= current:
            return self
        return self.model_copy(update={"last_uid": new_last_uid})
