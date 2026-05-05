"""FixDrawer: Receipt Fixer — Tkinter desktop GUI.

Thin shell over receipt_fixer.core.* — all business logic stays in
core. The conversion runs in a worker thread that talks to the main
loop through a thread-safe queue, polled every 50 ms.

Brand-voice contract: log headers are direct and technical
(VERIFICATION RUN, VERIFICATION PASSED, FAILURE FOUND,
FAILURE RISK CHECK). No apologies, no marketing copy.
"""
from __future__ import annotations

import csv
import errno
import logging
import queue
import sys
import tempfile
import threading
import tkinter as tk
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from fixdrawer_app_base import (
    ReadOnlyTextPanel,
    find_asset,
    folder_open_action,
)

from receipt_fixer.core.normalize import (
    UnsupportedFormatError,
    normalize_to_png,
)
from receipt_fixer.core.scanner import scan_input_folder
from receipt_fixer.release import APP_BRAND, APP_NAME, APP_VERSION

POLL_INTERVAL_MS = 50
DEFAULT_CSV_NAME = "receipts.csv"
LOGO_REL_PATH = "receipt_fixer/assets/receipt_fixer_logo.png"
README_REL_PATH = "README.md"
NOT_DO_SECTION_HEADING = "What it does NOT do"
CREDIT_LINE = "Built by Corey J. — terminusprotocol.io"
NOT_DO_FALLBACK = (
    f"Could not locate README.md to render '{NOT_DO_SECTION_HEADING}'."
)
WINDOW_DEFAULT_SIZE = "780x680"
WINDOW_MIN_SIZE = (720, 600)
LOG_PANEL_ROWS = 13
PREVIEW_PANEL_ROWS = 7
TAGLINE = (
    "Receipt photos → spreadsheet-ready CSV\n"
    "Local only. No cloud. No account. No subscription."
)
SECTION_RULE = "─" * 60

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker → main-loop messages
# ---------------------------------------------------------------------------

@dataclass
class _LogMsg:
    text: str


@dataclass
class _DoneMsg:
    csv_path: Path
    receipt_path: Path
    seen: int
    rows_in_csv: int
    fully: int
    partial: int
    skipped: int
    failed: int


@dataclass
class _FailureMsg:
    what_failed: str
    detail: str
    customer_impact: str
    required_fix: str


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _run_pipeline(
    folder: Path,
    csv_path: Path,
    receipt_path: Path,
    force: bool,
    q: "queue.Queue",
) -> None:
    """Worker entry: scan → normalize → OCR → extract → write CSV + receipt."""
    from receipt_fixer.core.ocr import (
        _check_tesseract,
        extract_text,
        tesseract_install_hint,
    )
    from receipt_fixer.core.extract import extract_fields
    from receipt_fixer.core.output import (
        CsvExistsError,
        CsvRow,
        CsvVerificationError,
        sha256_file,
        write_csv,
        write_verification_receipt,
    )

    try:
        _check_tesseract()
    except EnvironmentError:
        q.put(_FailureMsg(
            what_failed="Tesseract OCR binary not found on PATH",
            detail=tesseract_install_hint(),
            customer_impact="Cannot read text from receipt images.",
            required_fix="Install Tesseract using the steps above and relaunch.",
        ))
        return

    try:
        files = scan_input_folder(folder)
    except (FileNotFoundError, NotADirectoryError) as exc:
        q.put(_FailureMsg(
            what_failed="Input folder not found",
            detail=str(exc),
            customer_impact="No CSV produced.",
            required_fix=(
                f"Restore {folder} or choose a different folder, then "
                f"re-run."
            ),
        ))
        return
    except PermissionError as exc:
        q.put(_FailureMsg(
            what_failed="Input folder is not readable",
            detail=str(exc),
            customer_impact="No CSV produced.",
            required_fix=f"Grant read access on {folder} and re-run.",
        ))
        return
    except Exception as exc:  # noqa: BLE001
        q.put(_FailureMsg(
            what_failed="Could not scan input folder",
            detail=str(exc),
            customer_impact="No CSV produced.",
            required_fix=f"Confirm {folder} exists and is readable.",
        ))
        return

    q.put(_LogMsg(""))
    q.put(_LogMsg("VERIFICATION RUN"))
    q.put(_LogMsg(SECTION_RULE))
    q.put(_LogMsg(f"Input folder:  {folder}"))
    q.put(_LogMsg(f"Output CSV:    {csv_path}"))
    q.put(_LogMsg(f"Files seen:    {len(files)}"))
    q.put(_LogMsg(""))

    rows: list[CsvRow] = []
    seen = fully = partial = skipped = failed = 0

    with tempfile.TemporaryDirectory(prefix="receipt_fixer_") as tmp:
        work_dir = Path(tmp)
        for i, rf in enumerate(files, start=1):
            seen += 1
            label = f"[{i}/{len(files)}] {rf.path.name}"
            try:
                norm = normalize_to_png(rf, work_dir)
                ocr_result = extract_text(norm)
                extracted = extract_fields(ocr_result)
                row = CsvRow.from_extracted(rf.path.name, extracted)
                rows.append(row)
                conf = extracted.confidence
                if extracted.amount is not None and extracted.date is not None:
                    fully += 1
                    q.put(_LogMsg(f"{label}  ok       conf={conf:.1f}"))
                else:
                    partial += 1
                    reason = "; ".join(extracted.reasons) or "missing fields"
                    q.put(_LogMsg(
                        f"{label}  partial  conf={conf:.1f}  ({reason})"
                    ))
            except UnsupportedFormatError as exc:
                skipped += 1
                rows.append(CsvRow.skipped(rf.path.name, str(exc)))
                q.put(_LogMsg(f"{label}  skip     ({exc})"))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                q.put(_LogMsg(f"{label}  FAIL     ({exc})"))

    try:
        write_csv(rows, csv_path, force=force)
    except CsvExistsError as exc:
        q.put(_FailureMsg(
            what_failed="Output CSV already exists",
            detail=str(exc),
            customer_impact="Previous run preserved; no new CSV written.",
            required_fix="Choose a different output path or confirm overwrite.",
        ))
        return
    except CsvVerificationError as exc:
        q.put(_FailureMsg(
            what_failed="Post-write CSV verification failed",
            detail=str(exc),
            customer_impact=(
                "Refusing to deliver a CSV that does not pass its own "
                "integrity check."
            ),
            required_fix=(
                "Re-run; if this persists, capture the input folder and "
                "open an issue."
            ),
        ))
        return
    except PermissionError as exc:
        q.put(_FailureMsg(
            what_failed="Cannot write Output CSV: permission denied",
            detail=str(exc),
            customer_impact="No CSV produced.",
            required_fix=(
                f"Grant write access on {csv_path.parent} or choose a "
                f"different output location."
            ),
        ))
        return
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            q.put(_FailureMsg(
                what_failed="Cannot write Output CSV: disk full",
                detail=str(exc),
                customer_impact="No CSV produced.",
                required_fix=(
                    f"Free up space on the volume containing "
                    f"{csv_path.parent} and re-run."
                ),
            ))
            return
        q.put(_FailureMsg(
            what_failed="Could not write CSV",
            detail=f"{type(exc).__name__}: {exc}",
            customer_impact="No CSV produced.",
            required_fix=f"Check write permissions on {csv_path.parent}.",
        ))
        return
    except Exception as exc:  # noqa: BLE001
        q.put(_FailureMsg(
            what_failed="Could not write CSV",
            detail=f"{type(exc).__name__}: {exc}",
            customer_impact="No CSV produced.",
            required_fix=f"Check write permissions on {csv_path.parent}.",
        ))
        return

    try:
        write_verification_receipt(
            run_dt=datetime.now(),
            input_folder=folder,
            csv_path=csv_path,
            rows=rows,
            receipt_path=receipt_path,
        )
    except PermissionError as exc:
        q.put(_FailureMsg(
            what_failed="Cannot write verification receipt: permission denied",
            detail=str(exc),
            customer_impact=(
                "CSV is on disk but its verification receipt is missing."
            ),
            required_fix=f"Grant write access on {receipt_path.parent}.",
        ))
        return
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            q.put(_FailureMsg(
                what_failed="Cannot write verification receipt: disk full",
                detail=str(exc),
                customer_impact=(
                    "CSV is on disk but its verification receipt is missing."
                ),
                required_fix=(
                    f"Free up space on the volume containing "
                    f"{receipt_path.parent} and re-run."
                ),
            ))
            return
        q.put(_FailureMsg(
            what_failed="Could not write verification receipt",
            detail=f"{type(exc).__name__}: {exc}",
            customer_impact=(
                "CSV is on disk but its verification receipt is missing."
            ),
            required_fix=f"Check write permissions on {receipt_path.parent}.",
        ))
        return
    except Exception as exc:  # noqa: BLE001
        q.put(_FailureMsg(
            what_failed="Could not write verification receipt",
            detail=f"{type(exc).__name__}: {exc}",
            customer_impact=(
                "CSV is on disk but its verification receipt is missing."
            ),
            required_fix=f"Check write permissions on {receipt_path.parent}.",
        ))
        return

    csv_sha = sha256_file(csv_path)
    q.put(_LogMsg(""))
    q.put(_LogMsg("VERIFICATION PASSED"))
    q.put(_LogMsg(SECTION_RULE))
    q.put(_LogMsg(f"Files seen:        {seen}"))
    q.put(_LogMsg(f"Rows in CSV:       {len(rows)}"))
    q.put(_LogMsg(f"  fully extracted: {fully}"))
    q.put(_LogMsg(f"  partial:         {partial}"))
    q.put(_LogMsg(f"  skipped:         {skipped}"))
    q.put(_LogMsg(f"  failed:          {failed}"))
    q.put(_LogMsg(f"Output CSV:        {csv_path}"))
    q.put(_LogMsg(f"SHA-256 ({csv_path.name}): {csv_sha}"))
    q.put(_LogMsg(f"Receipt:           {receipt_path}"))

    q.put(_DoneMsg(
        csv_path=csv_path,
        receipt_path=receipt_path,
        seen=seen,
        rows_in_csv=len(rows),
        fully=fully,
        partial=partial,
        skipped=skipped,
        failed=failed,
    ))


# ---------------------------------------------------------------------------
# CSV preview helper
# ---------------------------------------------------------------------------

def _extract_readme_section(readme_text: str, heading: str) -> str:
    """Return the body of the README section under '## {heading}' as plain
    text. Stops at the next '## ' heading or end-of-file. Strips horizontal
    rules ('---') and Markdown bullet markers."""
    lines = readme_text.splitlines()
    target = f"## {heading}".strip().lower()
    in_section = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower() == target:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section:
            if stripped == "---":
                continue
            out.append(line)
    text = "\n".join(out).strip()
    return text


def _read_preview(csv_path: Path, max_rows: int = 7) -> str:
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = []
            for i, row in enumerate(reader):
                if i > max_rows:
                    break
                rows.append(" | ".join(row))
            return "\n".join(rows)
    except Exception as exc:  # noqa: BLE001
        return f"(could not preview CSV: {exc})"


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ReceiptFixerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_BRAND}: {APP_NAME} v{APP_VERSION}")
        root.geometry(WINDOW_DEFAULT_SIZE)
        root.minsize(*WINDOW_MIN_SIZE)

        self._folder: Optional[Path] = None
        self._csv: Optional[Path] = None
        self._queue: "queue.Queue" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._last_csv: Optional[Path] = None
        self._logo_image: Optional[tk.PhotoImage] = None  # keep ref alive

        self._about_logo: Optional[tk.PhotoImage] = None  # keep ref alive
        self._build_menu()
        self._build_ui()
        self._update_convert_state()

    # --- menu -----------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About", command=self._show_about)
        help_menu.add_command(
            label="What it does NOT do", command=self._show_not_do
        )
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menubar)

    def _show_about(self) -> None:
        win = tk.Toplevel(self.root)
        win.title(f"About {APP_NAME}")
        win.transient(self.root)
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=18)
        frame.pack(fill="both", expand=True)

        logo_path = find_asset(LOGO_REL_PATH)
        if logo_path is not None:
            try:
                self._about_logo = tk.PhotoImage(file=str(logo_path))
                ttk.Label(frame, image=self._about_logo).pack(pady=(0, 8))
            except tk.TclError as exc:
                logger.warning("could not load logo at %s: %s", logo_path, exc)

        ttk.Label(
            frame, text=APP_BRAND, font=("Helvetica", 11)
        ).pack()
        ttk.Label(
            frame, text=APP_NAME, font=("Helvetica", 16, "bold")
        ).pack()
        ttk.Label(frame, text=f"v{APP_VERSION}").pack(pady=(0, 8))
        ttk.Label(frame, text=CREDIT_LINE).pack()

        ttk.Button(frame, text="Close", command=win.destroy).pack(pady=(14, 0))
        win.grab_set()

    def _show_not_do(self) -> None:
        body = self._load_not_do_text()

        win = tk.Toplevel(self.root)
        win.title(NOT_DO_SECTION_HEADING)
        win.transient(self.root)
        win.geometry("560x420")

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text=NOT_DO_SECTION_HEADING,
            font=("Helvetica", 13, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        text_panel = ReadOnlyTextPanel(frame, height=18, wrap="word")
        text_panel.pack(fill="both", expand=True)
        text_panel.set_text(body)

        ttk.Button(frame, text="Close", command=win.destroy).pack(
            pady=(10, 0), anchor="e"
        )
        win.grab_set()

    def _load_not_do_text(self) -> str:
        readme = find_asset(README_REL_PATH)
        if readme is None:
            return NOT_DO_FALLBACK
        try:
            text = readme.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Could not read README.md: {exc}"
        section = _extract_readme_section(text, NOT_DO_SECTION_HEADING)
        return section or NOT_DO_FALLBACK

    # --- layout ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True, padx=18, pady=14)
        outer.columnconfigure(0, weight=1)

        # --- Logo (placeholder if absent) ---
        logo_path = find_asset(LOGO_REL_PATH)
        if logo_path is not None:
            try:
                self._logo_image = tk.PhotoImage(file=str(logo_path))
                ttk.Label(outer, image=self._logo_image).grid(
                    row=0, column=0, pady=(0, 4)
                )
            except tk.TclError as exc:
                logger.warning("could not load logo at %s: %s", logo_path, exc)

        # --- App name ---
        ttk.Label(
            outer, text=APP_NAME, font=("Helvetica", 22, "bold")
        ).grid(row=1, column=0, pady=(2, 2))

        # --- Tagline ---
        ttk.Label(
            outer, text=TAGLINE, justify="center",
            font=("Helvetica", 10),
        ).grid(row=2, column=0, pady=(0, 12))

        # --- Folder picker row ---
        folder_row = ttk.Frame(outer)
        folder_row.grid(row=3, column=0, sticky="ew", pady=4)
        folder_row.columnconfigure(1, weight=1)
        ttk.Button(
            folder_row, text="Choose folder of receipts",
            command=self._choose_folder,
        ).grid(row=0, column=0, padx=(0, 8))
        self._folder_label = ttk.Label(folder_row, text="(none selected)")
        self._folder_label.grid(row=0, column=1, sticky="w")

        # --- Output CSV picker row ---
        csv_row = ttk.Frame(outer)
        csv_row.grid(row=4, column=0, sticky="ew", pady=4)
        csv_row.columnconfigure(1, weight=1)
        ttk.Button(
            csv_row, text="Choose Output CSV",
            command=self._choose_csv,
        ).grid(row=0, column=0, padx=(0, 8))
        self._csv_label = ttk.Label(csv_row, text="(none selected)")
        self._csv_label.grid(row=0, column=1, sticky="w")

        # --- Action buttons ---
        action_row = ttk.Frame(outer)
        action_row.grid(row=5, column=0, sticky="ew", pady=(12, 8))
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=0)

        self._convert_btn = tk.Button(
            action_row, text="Convert and Verify",
            command=self._on_convert,
            font=("Helvetica", 12, "bold"),
            padx=12, pady=6,
        )
        self._convert_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self._open_btn = ttk.Button(
            action_row, text="Open Output Folder",
            command=folder_open_action(self._output_folder_supplier),
            state="disabled",
        )
        self._open_btn.grid(row=0, column=1)

        # --- Verification log panel ---
        ttk.Label(outer, text="Verification log:").grid(
            row=6, column=0, sticky="w", pady=(8, 2)
        )
        self._log_panel = ReadOnlyTextPanel(
            outer, height=LOG_PANEL_ROWS, wrap="word"
        )
        self._log_panel.grid(row=7, column=0, sticky="nsew", pady=(0, 8))
        outer.rowconfigure(7, weight=3)

        # --- Verified preview panel ---
        ttk.Label(outer, text="Verified output preview:").grid(
            row=8, column=0, sticky="w", pady=(4, 2)
        )
        self._preview_panel = ReadOnlyTextPanel(
            outer, height=PREVIEW_PANEL_ROWS, wrap="none"
        )
        self._preview_panel.grid(row=9, column=0, sticky="nsew")
        outer.rowconfigure(9, weight=1)

    # --- handlers --------------------------------------------------------

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose folder of receipts")
        if chosen:
            self._folder = Path(chosen)
            self._folder_label.configure(text=str(self._folder))
            self._update_convert_state()

    def _choose_csv(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Choose Output CSV",
            defaultextension=".csv",
            initialfile=DEFAULT_CSV_NAME,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            confirmoverwrite=False,  # we run our own FAILURE RISK CHECK
        )
        if chosen:
            self._csv = Path(chosen)
            self._csv_label.configure(text=str(self._csv))
            self._update_convert_state()

    def _on_convert(self) -> None:
        if self._folder is None or self._csv is None:
            return
        if self._worker is not None and self._worker.is_alive():
            return

        force = False
        if self._csv.exists():
            if not messagebox.askyesno(
                title="FAILURE RISK CHECK",
                message=(
                    f"{self._csv} already exists.\n\n"
                    f"Overwriting will destroy the previous CSV and its "
                    f"verification receipt. Proceed?"
                ),
                icon="warning",
            ):
                self._log_panel.append("FAILURE RISK CHECK declined — run aborted.")
                return
            force = True

        receipt_path = self._csv.with_suffix(self._csv.suffix + ".receipt.txt")

        self._log_panel.clear()
        self._preview_panel.clear()
        self._open_btn.configure(state="disabled")
        self._convert_btn.configure(state="disabled")

        self._worker = threading.Thread(
            target=self._worker_entry,
            kwargs={
                "folder": self._folder,
                "csv_path": self._csv,
                "receipt_path": receipt_path,
                "force": force,
            },
            daemon=True,
        )
        self._worker.start()
        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _worker_entry(self, **kwargs) -> None:
        try:
            _run_pipeline(q=self._queue, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._queue.put(_FailureMsg(
                what_failed=f"Unhandled {type(exc).__name__} in worker",
                detail=traceback.format_exc(),
                customer_impact="Conversion did not complete.",
                required_fix="Capture the trace above and open an issue.",
            ))

    # --- queue polling --------------------------------------------------

    def _poll_queue(self) -> None:
        finished = False
        try:
            while True:
                msg = self._queue.get_nowait()
                if isinstance(msg, _LogMsg):
                    self._log_panel.append(msg.text)
                elif isinstance(msg, _DoneMsg):
                    self._handle_done(msg)
                    finished = True
                elif isinstance(msg, _FailureMsg):
                    self._handle_failure(msg)
                    finished = True
        except queue.Empty:
            pass

        worker_done = self._worker is not None and not self._worker.is_alive()
        if finished or (worker_done and self._queue.empty()):
            self._convert_btn.configure(state=self._convert_state())
            return

        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _handle_done(self, msg: _DoneMsg) -> None:
        self._last_csv = msg.csv_path
        preview = _read_preview(msg.csv_path, max_rows=PREVIEW_PANEL_ROWS - 1)
        self._preview_panel.set_text(preview)
        self._open_btn.configure(state="normal")

    def _handle_failure(self, msg: _FailureMsg) -> None:
        self._log_panel.append("")
        self._log_panel.append("FAILURE FOUND")
        self._log_panel.append(SECTION_RULE)
        self._log_panel.append(f"What failed:      {msg.what_failed}")
        for line in msg.detail.splitlines() or [""]:
            self._log_panel.append(f"Detail:           {line}" if line else "")
        self._log_panel.append(f"Customer impact:  {msg.customer_impact}")
        self._log_panel.append(f"Required fix:     {msg.required_fix}")
        messagebox.showerror(
            title="FAILURE FOUND",
            message=f"{msg.what_failed}\n\n{msg.detail}",
        )

    # --- helpers --------------------------------------------------------

    def _output_folder_supplier(self) -> Optional[Path]:
        return self._last_csv.parent if self._last_csv is not None else None

    def _convert_state(self) -> str:
        return (
            "normal"
            if self._folder is not None and self._csv is not None
            else "disabled"
        )

    def _update_convert_state(self) -> None:
        self._convert_btn.configure(state=self._convert_state())


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s: %(message)s"
    )
    root = tk.Tk()
    ReceiptFixerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
