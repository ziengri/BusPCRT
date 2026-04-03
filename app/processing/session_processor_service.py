from __future__ import annotations

import time
import logging
from datetime import datetime
from pathlib import Path

from app.ai.session_ai_runner import SessionAIRunner
from app.door.door_state_reader import DoorStateReader
from app.processing.result_sink import ResultSink
from app.shared.session_storage import (
    SessionDirs,
    delete_session_pair,
    list_ready_meta_oldest_first,
    move_session_pair,
)
from app.shared.types import ProcessedResult
from video_session import SessionMeta


class SessionProcessorService:
    """Processes ready sessions oldest-first."""

    def __init__(
        self,
        door_reader: DoorStateReader,
        ai_runner: SessionAIRunner,
        result_sink: ResultSink,
        session_dirs: SessionDirs,
        idle_sleep_s: float = 0.5,
    ):
        self.door_reader = door_reader
        self.ai_runner = ai_runner
        self.result_sink = result_sink
        self.session_dirs = session_dirs
        self.idle_sleep_s = float(idle_sleep_s)
        self.session_dirs.ensure_exists()
        self._logger = logging.getLogger(__name__)

    def _pick_oldest_ready(self) -> Path | None:
        ordered = list_ready_meta_oldest_first(self.session_dirs.ready)
        return ordered[0] if ordered else None

    @staticmethod
    def _date_from_meta(meta: SessionMeta) -> str:
        dt = datetime.fromtimestamp(meta.timestamp / 1000.0)
        return dt.strftime("%d.%m.%YT%H:%M")

    def process_one_if_allowed(self) -> bool:
        ready_meta = self._pick_oldest_ready()
        if ready_meta is None:
            # self._logger.debug("No ready sessions found")
            return False

        processing_meta = move_session_pair(ready_meta, self.session_dirs.processing)
        try:
            meta = SessionMeta.load(processing_meta)
            self._logger.info("Run AI processing,session: %s", processing_meta.name)
            count_result = self.ai_runner.run_session(processing_meta)
            self.result_sink.write(
                ProcessedResult(
                    date=self._date_from_meta(meta),
                    id=meta.id,
                    total_in=count_result.total_in,
                    total_out=count_result.total_out,
                    meta_path=processing_meta,
                )
            )
            self._logger.info("Complete AI processing,session: %s", processing_meta.name)

            delete_session_pair(processing_meta)
        except Exception:  # noqa: BLE001
            move_session_pair(processing_meta, self.session_dirs.failed)
            self._logger.exception("Session processing failed: %s", processing_meta.name)
            raise
        return True

    def run_forever(self) -> None:
        while True:
            processed = False
            try:
                processed = self.process_one_if_allowed()
            except Exception:  # noqa: BLE001
                self._logger.exception("Processor loop error")

            if not processed:
                time.sleep(self.idle_sleep_s)
