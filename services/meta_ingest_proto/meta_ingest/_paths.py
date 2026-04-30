"""저장소 루트·libs 를 sys.path 에 넣는다."""

from __future__ import annotations

import sys
from pathlib import Path


def _libs_dir() -> Path:
    here = Path(__file__).resolve().parent  # .../meta_ingest
    # Docker: /app/meta_ingest + /app/libs
    candidate = here.parent / "libs"
    if candidate.is_dir():
        return candidate
    # 로컬: .../services/meta_ingest_proto/meta_ingest → repo 루트 libs
    return here.parents[3] / "libs"


_LIBS = _libs_dir()

if str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))
