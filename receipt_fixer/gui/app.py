"""Tkinter desktop GUI for Receipt Fixer.

Thin shell over receipt_fixer.core.* — all business logic stays in core.
The conversion runs in a worker thread that communicates with the main
loop via a thread-safe queue, polled every 50 ms.
"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from receipt_fixer.core.normalize import (
    UnsupportedFormatError,
    normalize_to_png,
)
from receipt_fixer.core.scanner import scan_input_folder

POLL_INTERVAL_MS = 50
DEFAULT_THRESHOLD = 60
DEFAULT_CSV_NAME = "receipts.csv"
WINDOW_TITLE = "Receipt Fixer"
WINDOW_DEFAULT_SIZE = "720x520"
WINDOW_MIN_SIZE = (640, 460)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker → main-loop messages
# ---------------------------------------------------------------------------

@dataclass
class _LogMsg:
    text: str


@dataclass
class _ProgressInit:
    total: int


@dataclass
class _ProgressTick:
    current: int


@dataclass
class _DoneMsg:
    csv_path: Path
    receipt_path: Path
    seen: int
    rows: int
    skipped: int
    failed: int
    low_conf: int


@dataclass
class _ErrorMsg:
    title: str
    detail: str


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _open_in_file_manager(path: Path) -> None:
    """Open *path* in the OS file manager. Best-effort, never raises."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        logger.warning("could not open file manager for %s: %s", path, exc)


def _run_pipeline(
    folder: Path,
    csv_path: Path,
    receipt_path: Path,
    force: bool,
    threshold: float,
    q: "queue.Queue",
) -> None:
    """Worker entry point. Runs scan → normalize → OCR → extract → write."""
    # Imports that depend on Tesseract are lazy so the GUI starts even if
    # the binary is missing — we only fail when the user clicks Convert.
    from receipt_fixer.core.ocr import _check_tesseract, extract_text
    from receipt_fixer.core.extract import extract_fields
    from receipt_fixer.core.output import (
        CsvExistsError,
        CsvRow,
        CsvVerificationError,
        write_csv,
        write_verification_receipt,
    )

    try:
        _check_tesseract()
    except EnvironmentError as exc:
        q.put(_ErrorMsg(title="Tesseract not found", detail=str(exc)))
        return

    try:
        files = scan_input_folder(folder)
    except Exception as exc:
        q.put(_ErrorMsg(title="Could not scan folder", detail=str(exc)))
        return

    q.put(_LogMsg(f"Found {len(files)} files in {folder}"))
    q.put(_ProgressInit(total=max(len(files), 1)))

    rows: list[CsvRow] = []
    seen = skipped = failed = low_conf = 0

    with tempfile.TemporaryDirectory(prefix="receipt_fixer_") as tmp:
        work_dir = Path(tmp)
        for i, rf in enumerate(files, start=1):
            seen += 1
            try:
                norm = normalize_to_png(rf, work_dir)
                ocr_result = extract_text(norm)
                extracted = extract_fields(ocr_result)
                row = CsvRow.from_extracted(rf.path.name, extracted)
                rows.append(row)

                conf = extracted.confidence
                if conf < threshold:
                    low_conf += 1
                    q.put(_LogMsg(
                        f"  LOW  conf={conf:.1f}  {rf.path.name}"
                    ))
                elif extracted.amount is None or extracted.date is None:
                    q.put(_LogMsg(
                        f"  partial  conf={conf:.1f}  {rf.path.name}  "
                        f"({'; '.join(extracted.reasons) or 'missing fields'})"
                    ))
                else:
                    q.put(_LogMsg(
                        f"  ok    conf={conf:.1f}  {rf.path.name}"
                    ))
            except UnsupportedFormatError as exc:
                skipped += 1
                rows.append(CsvRow.skipped(rf.path.name, str(exc)))
                q.put(_LogMsg(f"  skip  {rf.path.name} ({exc})"))
            except Exception as exc:
                failed += 1
                q.put(_LogMsg(f"  FAIL  {rf.path.name} ({exc})"))
            q.put(_ProgressTick(current=i))

    try:
        write_csv(rows, csv_path, force=force)
    except CsvExistsError as exc:
        q.put(_ErrorMsg(title="Output file exists", detail=str(exc)))
        return
    except CsvVerificationError as exc:
        q.put(_ErrorMsg(
            title="CSV verification failed",
            detail=f"The output CSV did not pass post-write verification.\n\n{exc}",
        ))
        return
    except Exception as exc:
        q.put(_ErrorMsg(title="Could not write CSV", detail=str(exc)))
        return

    try:
        write_verification_receipt(
            run_dt=datetime.now(),
            input_folder=folder,
            csv_path=csv_path,
            rows=rows,
            receipt_path=receipt_path,
        )
    except Exception as exc:
        q.put(_ErrorMsg(
            title="Could not write verification receipt",
            detail=str(exc),
        ))
        return

    q.put(_DoneMsg(
        csv_path=csv_path,
        receipt_path=receipt_path,
        seen=seen,
        rows=len(rows),
        skipped=skipped,
        failed=failed,
        low_conf=low_conf,
    ))


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ReceiptFixerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(WINDOW_TITLE)
        root.geometry(WINDOW_DEFAULT_SIZE)
        root.minsize(*WINDOW_MIN_SIZE)

        self._folder: Optional[Path] = None
        self._csv: Optional[Path] = None
        self._queue: "queue.Queue" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._last_output_folder: Optional[Path] = None

        self._build_ui()
        self._update_convert_state()

    # --- layout ---------------------------------------------------------

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True, padx=10, pady=10)
        outer.columnconfigure(0, weight=1)

        # --- Input folder ---
        in_frame = ttk.LabelFrame(outer, text="Input folder")
        in_frame.grid(row=0, column=0, sticky="ew", **pad)
        in_frame.columnconfigure(1, weight=1)

        ttk.Button(
            in_frame, text="Choose folder…", command=self._choose_folder
        ).grid(row=0, column=0, padx=8, pady=8)
        self._folder_label = ttk.Label(in_frame, text="(none selected)")
        self._folder_label.grid(row=0, column=1, sticky="w", padx=4, pady=8)

        # --- Output CSV ---
        out_frame = ttk.LabelFrame(outer, text="Output CSV")
        out_frame.grid(row=1, column=0, sticky="ew", **pad)
        out_frame.columnconfigure(1, weight=1)

        ttk.Button(
            out_frame, text="Choose file…", command=self._choose_csv
        ).grid(row=0, column=0, padx=8, pady=8)
        self._csv_label = ttk.Label(out_frame, text="(none selected)")
        self._csv_label.grid(row=0, column=1, sticky="w", padx=4, pady=8)

        # --- Confidence threshold ---
        thr_frame = ttk.LabelFrame(outer, text="Confidence threshold")
        thr_frame.grid(row=2, column=0, sticky="ew", **pad)
        thr_frame.columnconfigure(0, weight=1)

        self._threshold_var = tk.IntVar(value=DEFAULT_THRESHOLD)
        self._threshold_label = ttk.Label(
            thr_frame, text=str(DEFAULT_THRESHOLD), width=4, anchor="e"
        )
        slider = ttk.Scale(
            thr_frame, from_=0, to=100, orient="horizontal",
            command=self._on_threshold_change,
        )
        slider.set(DEFAULT_THRESHOLD)
        slider.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self._threshold_label.grid(row=0, column=1, padx=8, pady=8)

        # --- Convert + progress ---
        action_frame = ttk.Frame(outer)
        action_frame.grid(row=3, column=0, sticky="ew", **pad)
        action_frame.columnconfigure(1, weight=1)

        self._convert_btn = ttk.Button(
            action_frame, text="Convert", command=self._on_convert
        )
        self._convert_btn.grid(row=0, column=0, padx=4, pady=4)

        self._progress = ttk.Progressbar(
            action_frame, mode="determinate", maximum=1
        )
        self._progress.grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        # --- Status log ---
        log_frame = ttk.LabelFrame(outer, text="Status")
        log_frame.grid(row=4, column=0, sticky="nsew", **pad)
        outer.rowconfigure(4, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self._log_text = tk.Text(
            log_frame, height=10, wrap="word", state="disabled",
            font=("TkFixedFont",),
        )
        self._log_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self._log_text.yview
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self._log_text.configure(yscrollcommand=log_scroll.set)

        # --- Summary banner + open output folder ---
        self._summary_var = tk.StringVar(value="")
        summary_frame = ttk.Frame(outer)
        summary_frame.grid(row=5, column=0, sticky="ew", **pad)
        summary_frame.columnconfigure(0, weight=1)

        self._summary_label = ttk.Label(
            summary_frame, textvariable=self._summary_var,
            foreground="#0a6", anchor="w",
        )
        self._summary_label.grid(row=0, column=0, sticky="ew")

        self._open_btn = ttk.Button(
            summary_frame, text="Open output folder",
            command=self._on_open_output,
            state="disabled",
        )
        self._open_btn.grid(row=0, column=1, padx=4)

    # --- event handlers --------------------------------------------------

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose input folder")
        if chosen:
            self._folder = Path(chosen)
            self._folder_label.configure(text=str(self._folder))
            self._update_convert_state()

    def _choose_csv(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Choose output CSV",
            defaultextension=".csv",
            initialfile=DEFAULT_CSV_NAME,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            confirmoverwrite=False,  # we do our own confirm via CsvExistsError path
        )
        if chosen:
            self._csv = Path(chosen)
            self._csv_label.configure(text=str(self._csv))
            self._update_convert_state()

    def _on_threshold_change(self, value: str) -> None:
        try:
            ival = int(round(float(value)))
        except ValueError:
            return
        self._threshold_var.set(ival)
        self._threshold_label.configure(text=str(ival))

    def _on_convert(self) -> None:
        if self._folder is None or self._csv is None:
            return
        if self._worker is not None and self._worker.is_alive():
            return

        force = False
        if self._csv.exists():
            if not messagebox.askyesno(
                title="Overwrite existing file?",
                message=(
                    f"{self._csv} already exists.\n\n"
                    f"Overwrite it? The previous CSV will be lost."
                ),
                icon="warning",
            ):
                return
            force = True

        receipt_path = self._csv.with_suffix(self._csv.suffix + ".receipt.txt")

        # Reset UI state for a new run.
        self._set_log("")
        self._summary_var.set("")
        self._progress.configure(value=0, maximum=1)
        self._open_btn.configure(state="disabled")
        self._convert_btn.configure(state="disabled")
        self._append_log(f"Starting conversion: {self._folder} → {self._csv}")

        self._worker = threading.Thread(
            target=_run_pipeline,
            kwargs={
                "folder": self._folder,
                "csv_path": self._csv,
                "receipt_path": receipt_path,
                "force": force,
                "threshold": float(self._threshold_var.get()),
                "q": self._queue,
            },
            daemon=True,
        )
        self._worker.start()
        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _on_open_output(self) -> None:
        if self._last_output_folder is not None:
            _open_in_file_manager(self._last_output_folder)

    # --- queue polling ---------------------------------------------------

    def _poll_queue(self) -> None:
        finished = False
        try:
            while True:
                msg = self._queue.get_nowait()
                if isinstance(msg, _LogMsg):
                    self._append_log(msg.text)
                elif isinstance(msg, _ProgressInit):
                    self._progress.configure(value=0, maximum=msg.total)
                elif isinstance(msg, _ProgressTick):
                    self._progress.configure(value=msg.current)
                elif isinstance(msg, _DoneMsg):
                    self._handle_done(msg)
                    finished = True
                elif isinstance(msg, _ErrorMsg):
                    self._handle_error(msg)
                    finished = True
        except queue.Empty:
            pass

        if finished or (self._worker is not None and not self._worker.is_alive()
                        and self._queue.empty()):
            self._convert_btn.configure(state=self._convert_state())
            return

        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _handle_done(self, msg: _DoneMsg) -> None:
        self._append_log("")
        self._append_log(f"Wrote CSV:     {msg.csv_path}")
        self._append_log(f"Wrote receipt: {msg.receipt_path}")
        self._summary_var.set(
            f"Done. Files seen: {msg.seen} · Rows written: {msg.rows} · "
            f"Skipped: {msg.skipped} · Failed: {msg.failed} · "
            f"Low confidence: {msg.low_conf}"
        )
        self._last_output_folder = msg.csv_path.parent
        self._open_btn.configure(state="normal")

    def _handle_error(self, msg: _ErrorMsg) -> None:
        self._append_log(f"ERROR: {msg.title} — {msg.detail}")
        messagebox.showerror(title=msg.title, message=msg.detail)

    # --- helpers ---------------------------------------------------------

    def _set_log(self, text: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        if text:
            self._log_text.insert("end", text)
        self._log_text.configure(state="disabled")

    def _append_log(self, line: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", line + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _convert_state(self) -> str:
        return "normal" if self._folder is not None and self._csv is not None else "disabled"

    def _update_convert_state(self) -> None:
        self._convert_btn.configure(state=self._convert_state())


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    root = tk.Tk()
    ReceiptFixerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
