"""kweon 최소 설정 — hyodo 패키지 DATA_DIR."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
