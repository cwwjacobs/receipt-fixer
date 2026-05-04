"""Reusable Tk widgets shared across FixDrawer apps.

`ReadOnlyTextPanel` — a Text widget that the user can scroll and select
text from but cannot edit. Used for the verification log and CSV
preview panes so log output cannot be tampered with mid-run.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional


class ReadOnlyTextPanel(ttk.Frame):
    """A scrollable read-only Text widget framed by a Scrollbar.

    Editing is suppressed by toggling `state` to "disabled" outside of
    the panel's own append/set/clear methods. Selection and copy still
    work because Tk's Text widget allows them in the disabled state.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 10,
        wrap: str = "word",
        font: Optional[tuple] = None,
        **frame_kwargs,
    ) -> None:
        super().__init__(master, **frame_kwargs)

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._text = tk.Text(
            self,
            height=height,
            wrap=wrap,
            state="disabled",
            font=font or ("TkFixedFont",),
            borderwidth=1,
            relief="solid",
        )
        self._scroll = ttk.Scrollbar(
            self, orient="vertical", command=self._text.yview
        )
        self._text.configure(yscrollcommand=self._scroll.set)

        self._text.grid(row=0, column=0, sticky="nsew")
        self._scroll.grid(row=0, column=1, sticky="ns")

    # --- public API -----------------------------------------------------

    def append(self, text: str) -> None:
        """Append *text* to the panel, ensuring a trailing newline."""
        self._text.configure(state="normal")
        self._text.insert("end", text)
        if not text.endswith("\n"):
            self._text.insert("end", "\n")
        self._text.see("end")
        self._text.configure(state="disabled")

    def append_lines(self, lines) -> None:
        for line in lines:
            self.append(line)

    def set_text(self, text: str) -> None:
        """Replace all panel contents with *text*."""
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        if text:
            self._text.insert("end", text)
        self._text.configure(state="disabled")

    def clear(self) -> None:
        self.set_text("")

    @property
    def text_widget(self) -> tk.Text:
        """Escape hatch for callers that need raw Text access (tags, etc)."""
        return self._text
