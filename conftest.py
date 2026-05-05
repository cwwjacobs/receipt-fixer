"""Make tests find vendored fixdrawer_app_base under src/.

Runtime launchers add src/ to PYTHONPATH; pytest needs the same."""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
