"""Cross-platform helpers for FixDrawer Tk apps.

`find_asset`     — locate a bundled file on disk (works in dev and inside
                   a PyInstaller `_MEIPASS` bundle).
`open_folder`    — reveal a directory in the OS file manager.
`folder_open_action` — Button-command factory that lazily resolves the
                   target path each time it is clicked.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]


def _candidate_roots() -> list[Path]:
    """Directories where a bundled asset might live.

    Order matters: PyInstaller bundle root first, then the running
    script's directory, then walked-up parents (so callers can be
    invoked from anywhere inside the repo).
    """
    roots: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))

    here = Path(__file__).resolve()
    roots.append(here.parent)
    roots.extend(here.parents)

    cwd = Path.cwd().resolve()
    if cwd not in roots:
        roots.append(cwd)

    return roots


def find_asset(rel_path: PathLike) -> Optional[Path]:
    """Return the first existing path for *rel_path* across known roots,
    or None if no candidate exists. Never raises."""
    rel = Path(rel_path)
    if rel.is_absolute():
        return rel if rel.exists() else None

    for root in _candidate_roots():
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def open_folder(path: PathLike) -> bool:
    """Open *path* in the OS file manager. Returns True on dispatch.

    Best-effort only — never raises. Logs a warning if the dispatch
    fails (e.g. xdg-open absent on a minimal Linux box).
    """
    p = Path(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("open_folder failed for %s: %s", p, exc)
        return False


def folder_open_action(
    path_or_supplier: Union[PathLike, Callable[[], Optional[PathLike]]],
) -> Callable[[], None]:
    """Build a Button-command callable that opens a folder when invoked.

    Accepts either a fixed path or a zero-arg callable that returns the
    path (so the target can change after the button is constructed —
    e.g. once a conversion finishes and a real output dir is known).
    A None return from the supplier is treated as 'no-op'.
    """

    def _action() -> None:
        if callable(path_or_supplier):
            target = path_or_supplier()
        else:
            target = path_or_supplier
        if target is None:
            return
        open_folder(target)

    return _action
