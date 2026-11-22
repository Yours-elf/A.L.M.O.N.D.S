"""
almonds_app.py -- A.L.M.O.N.D.S (A Lot of Math On Neat Data Sheets)

Tkinter GUI, event handling and output rendering.  All statistics live in
``stats_engine.py``; this file only collects choices from the user, calls the
engine, and displays the formatted results.

Run from the project root with either:

    python almonds/almonds_app.py
    python -m almonds.almonds_app
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

try:
    from almonds import stats_engine as engine
except ModuleNotFoundError as _exc:  # pragma: no cover - import plumbing
    if _exc.name in ("almonds", "almonds.stats_engine"):
        # Launched as a plain script: almonds/ is already on sys.path.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import stats_engine as engine  # type: ignore[no-redef]
    else:
        sys.exit(
            f"Missing required package '{_exc.name}'.\n"
            "Install the dependencies with:  pip install -r requirements.txt"
        )

import pandas as pd

APP_NAME = engine.APP_NAME
APP_TAGLINE = engine.APP_TAGLINE

# ----- Almond palette ------------------------------------------------------- #
BG = "#FAF5EF"          # cream / almond background
CARD = "#F2E8DC"        # soft card panels
TEXT = "#3B2F2F"        # rich espresso text
ACCENT = "#A67B5B"      # warm brown accent
ACCENT_DARK = "#8A6244"
BORDER = "#C8A883"      # light brown border
FIELD_BG = "#FFFDFA"
SELECT_BG = "#D9BFA3"
STRIPE = "#F7EFE5"

MAX_PREVIEW_ROWS = 1000
WINDOW_ALPHA = 0.96


# =========================================================================== #
# Modal variable-selection dialog
# =========================================================================== #
class AnalysisDialog(tk.Toplevel):
    """
    A small, reusable modal dialog built from field specifications.

    Each field is a dict with a ``kind``:

    * ``combo``  - read-only drop-down.  keys: key, label, options, default
    * ``list``   - multi-select list.    keys: key, label, options, default (list), height, width
    * ``entry``  - text entry.           keys: key, label, default, hint
    * ``check``  - check box.            keys: key, label, default (bool)
    * ``info``   - static text.          keys: label

    Add ``"required": True`` to a combo/list to force a selection.
    ``show()`` returns ``{key: value}`` or ``None`` if cancelled.
    """

    def __init__(self, parent: tk.Misc, title: str, fields: list, prompt: str | None = None, ok_text: str = "Run"):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=CARD, highlightthickness=3, highlightbackground=BORDER, highlightcolor=BORDER)
        self.transient(parent)
        self.result = None
        self._fields = fields
        self._widgets: dict = {}

        body = ttk.Frame(self, style="Card.TFrame", padding=(16, 14, 16, 8))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(0, 4))
        if prompt:
            ttk.Label(body, text=prompt, style="Card.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(0, 10))
        for spec in fields:
            self._add_field(body, spec)

        bar = ttk.Frame(self, style="Card.TFrame", padding=(16, 4, 16, 14))
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", command=self._cancel, style="Ghost.TButton").pack(side="right", padx=(8, 0))
        ttk.Button(bar, text=ok_text, command=self._ok).pack(side="right")

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = parent.winfo_rootx() + max((parent.winfo_width() - w) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - h) // 3, 0)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:  # window not viewable on some platforms - dialog still works
            pass
        self.focus_set()

    # ---- field construction ------------------------------------------------ #
    def _add_field(self, parent: ttk.Frame, spec: dict) -> None:
        kind = spec["kind"]
        label = spec.get("label", "")
        if kind == "info":
            ttk.Label(parent, text=label, style="Card.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(0, 8))
            return
        if kind == "check":
            var = tk.BooleanVar(value=bool(spec.get("default", False)))
            ttk.Checkbutton(parent, text=label, variable=var, style="Card.TCheckbutton").pack(anchor="w", pady=(0, 4))
            self._widgets[spec["key"]] = ("check", var, None)
            return

        ttk.Label(parent, text=label, style="CardBold.TLabel").pack(anchor="w", pady=(4, 2))
        if kind == "combo":
            var = tk.StringVar(value=spec.get("default", ""))
            cb = ttk.Combobox(parent, textvariable=var, values=list(spec["options"]), state="readonly", width=42)
            cb.pack(anchor="w", pady=(0, 6))
            self._widgets[spec["key"]] = ("combo", var, spec)
        elif kind == "entry":
            var = tk.StringVar(value=spec.get("default", ""))
            ttk.Entry(parent, textvariable=var, width=46).pack(anchor="w", pady=(0, 2))
            if spec.get("hint"):
                ttk.Label(parent, text=spec["hint"], style="Hint.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(0, 6))
            self._widgets[spec["key"]] = ("entry", var, spec)
        elif kind == "list":
            options = list(spec["options"])
            box = ttk.Frame(parent, style="Card.TFrame")
            box.pack(fill="both", expand=True, pady=(0, 2))
            lb = tk.Listbox(
                box,
                selectmode="extended",
                exportselection=False,
                height=spec.get("height", min(max(len(options), 4), 10)),
                width=spec.get("width", 40),
                bg=FIELD_BG,
                fg=TEXT,
                selectbackground=ACCENT,
                selectforeground="white",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                relief="flat",
                activestyle="none",
            )
            sb = ttk.Scrollbar(box, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            lb.pack(side="left", fill="both", expand=True)
            sb.pack(side="left", fill="y")
            defaults = set(spec.get("default", []) or [])
            for i, opt in enumerate(options):
                lb.insert("end", opt)
                if opt in defaults:
                    lb.selection_set(i)
            btns = ttk.Frame(parent, style="Card.TFrame")
            btns.pack(anchor="w", pady=(2, 6))
            ttk.Button(btns, text="Select all", style="Small.TButton", command=lambda: lb.selection_set(0, "end")).pack(side="left")
            ttk.Button(btns, text="Clear", style="Small.TButton", command=lambda: lb.selection_clear(0, "end")).pack(side="left", padx=6)
            self._widgets[spec["key"]] = ("list", lb, options)

    # ---- results ----------------------------------------------------------- #
    def _collect(self) -> dict:
        values = {}
        for spec in self._fields:
            if spec["kind"] == "info":
                continue
            kind, widget, extra = self._widgets[spec["key"]]
            if kind in ("combo", "entry"):
                values[spec["key"]] = widget.get().strip()
            elif kind == "check":
                values[spec["key"]] = bool(widget.get())
            elif kind == "list":
                values[spec["key"]] = [extra[i] for i in widget.curselection()]
        return values

    def _ok(self) -> None:
        values = self._collect()
        for spec in self._fields:
            if spec.get("required") and not values.get(spec.get("key", ""), True):
                what = spec.get("label", "an option").rstrip(":").lower()
                messagebox.showwarning(APP_NAME, f"Please choose {what}.", parent=self)
                return
        self.result = values
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


# =========================================================================== #
# Main application window
# =========================================================================== #
class AlmondsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.df: pd.DataFrame | None = None
        self.path: str | None = None
        self.log_entries: list = []

        self._setup_window()
        self._setup_fonts()
        self._setup_style()
        self._build_header()
        self._build_toolbar()
        self._build_menubar()
        self._build_workspace()
        self._build_statusbar()
        self._write_welcome()
        self.root.bind("<Control-o>", lambda _e: self.cmd_open())
        self.root.bind("<Control-e>", lambda _e: self.cmd_export_log())
        self._set_status("Ready. Open a CSV, TSV or Excel file to begin (File > Open Data...).")

    # ---- window / theme ---------------------------------------------------- #
    def _setup_window(self) -> None:
        root = self.root
        root.title(f"{APP_NAME} - {APP_TAGLINE}")
        root.configure(bg=BORDER)  # light-brown outer border shows around the main frame
        w, h = 1220, 780
        x = max((root.winfo_screenwidth() - w) // 2, 0)
        y = max((root.winfo_screenheight() - h) // 2 - 20, 0)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(960, 600)
        try:
            root.attributes("-alpha", WINDOW_ALPHA)  # subtle window transparency
        except tk.TclError:
            pass  # not supported on every window manager

        # Main framed container: inner border ring + padding gives the brown outline.
        self.main = tk.Frame(
            root, bg=BG, highlightthickness=3, highlightbackground=ACCENT, highlightcolor=ACCENT, bd=0
        )
        self.main.pack(fill="both", expand=True, padx=7, pady=7)

    def _setup_fonts(self) -> None:
        base = tkfont.nametofont("TkDefaultFont")
        self.ui_family = base.actual("family")
        base.configure(size=10)
        available = set(tkfont.families(self.root))
        self.mono_family = None
        for fam in ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Liberation Mono", "Courier New"):
            if fam in available:
                self.mono_family = fam
                break
        if self.mono_family is None:
            self.mono_family = tkfont.nametofont("TkFixedFont").actual("family")

    def _setup_style(self) -> None:
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        fam = self.ui_family
        st.configure(".", background=BG, foreground=TEXT, font=(fam, 10), bordercolor=BORDER, focuscolor=ACCENT)
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("Card.TLabel", background=CARD, foreground=TEXT)
        st.configure("CardBold.TLabel", background=CARD, foreground=TEXT, font=(fam, 10, "bold"))
        st.configure("CardTitle.TLabel", background=CARD, foreground=ACCENT_DARK, font=(fam, 13, "bold"))
        st.configure("Hint.TLabel", background=CARD, foreground=ACCENT_DARK, font=(fam, 9, "italic"))
        st.configure("Logo.TLabel", background=CARD, foreground=ACCENT, font=(fam, 22, "bold"))
        st.configure("Tag.TLabel", background=CARD, foreground=TEXT, font=(fam, 10, "italic"))
        st.configure("Section.TLabel", background=CARD, foreground=ACCENT_DARK, font=(fam, 11, "bold"))
        st.configure("Status.TLabel", background=CARD, foreground=TEXT, padding=(8, 4))
        st.configure("TButton", background=ACCENT, foreground="white", padding=(12, 6), borderwidth=0, focusthickness=0, relief="flat")
        st.map("TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK)])
        st.configure("Ghost.TButton", background=BORDER, foreground=TEXT)
        st.map("Ghost.TButton", background=[("active", SELECT_BG), ("pressed", SELECT_BG)])
        st.configure("Small.TButton", padding=(8, 2), font=(fam, 9))
        st.configure("TMenubutton", background=ACCENT, foreground="white", padding=(12, 6), borderwidth=0, relief="flat", arrowcolor="white")
        st.map("TMenubutton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK)])
        st.configure("Card.TCheckbutton", background=CARD, foreground=TEXT)
        st.map("Card.TCheckbutton", background=[("active", CARD)])
        st.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT)
        st.configure("TCombobox", fieldbackground=FIELD_BG, background=CARD, foreground=TEXT, arrowcolor=TEXT)
        st.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD_BG)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", FIELD_BG)],
            selectforeground=[("readonly", TEXT)],
        )
        self.root.option_add("*TCombobox*Listbox.background", FIELD_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
        st.configure("TNotebook.Tab", background=CARD, foreground=TEXT, padding=(18, 7), borderwidth=0, font=(fam, 10, "bold"))
        st.map("TNotebook.Tab", background=[("selected", ACCENT), ("active", SELECT_BG)], foreground=[("selected", "white")])
        st.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG, foreground=TEXT, rowheight=23, borderwidth=0)
        st.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", TEXT)])
        st.configure("Treeview.Heading", background=ACCENT, foreground="white", relief="flat", font=(fam, 10, "bold"), padding=(6, 4))
        st.map("Treeview.Heading", background=[("active", ACCENT_DARK)])
        for orient in ("Vertical", "Horizontal"):
            st.configure(f"{orient}.TScrollbar", background=CARD, troughcolor=BG, bordercolor=BORDER, arrowcolor=TEXT, relief="flat")
        st.configure("TPanedwindow", background=BG)

    # ---- layout ------------------------------------------------------------ #
    def _build_header(self) -> None:
        head = ttk.Frame(self.main, style="Card.TFrame", padding=(14, 8))
        head.pack(fill="x")
        ttk.Label(head, text=APP_NAME, style="Logo.TLabel").pack(side="left")
        ttk.Label(head, text=f"  {APP_TAGLINE}", style="Tag.TLabel").pack(side="left", pady=(8, 0))
        self.dataset_label = ttk.Label(head, text="No dataset loaded", style="Tag.TLabel")
        self.dataset_label.pack(side="right", pady=(8, 0))

    def _menu_spec(self) -> list:
        """(group title, [(label, command) | None for separator])"""
        return [
            ("File", [("Open Data...  (Ctrl+O)", self.cmd_open), ("Close Dataset", self.cmd_close), None, ("Exit", self.root.destroy)]),
            ("Data Inspection", [("Inspect Data (types, counts, missing values)", self.cmd_inspect)]),
            (
                "Descriptive Stats",
                [
                    ("Univariate Summary...", self.cmd_univariate),
                    ("Distribution Metrics (quartiles, percentiles, skew, kurtosis)...", self.cmd_distribution),
                    None,
                    ("Frequency Table...", self.cmd_frequency),
                    ("Cross-Tabulation...", self.cmd_crosstab),
                ],
            ),
            (
                "Hypothesis Tests",
                [("Chi-Square Test of Independence...", self.cmd_chi_independence), ("Chi-Square Goodness-of-Fit...", self.cmd_chi_gof)],
            ),
            (
                "Correlation & Regression",
                [("Correlation Matrix (Pearson & Spearman)...", self.cmd_correlation), ("Linear Regression (OLS)...", self.cmd_regression)],
            ),
            (
                "Export Output",
                [
                    ("Export Output Log...  (Ctrl+E)", self.cmd_export_log),
                    ("Export Selected Result Tables...", self.cmd_export_tables),
                    None,
                    ("Clear Output Log", self.cmd_clear_log),
                ],
            ),
        ]

    def _new_menu(self, parent: tk.Misc) -> tk.Menu:
        return tk.Menu(parent, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground="white", relief="flat", bd=1)

    def _populate(self, menu: tk.Menu, items: list) -> None:
        for item in items:
            if item is None:
                menu.add_separator()
            else:
                menu.add_command(label=item[0], command=item[1])

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.main, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Open Data", command=self.cmd_open).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Inspect Data", command=self.cmd_inspect).pack(side="left", padx=6)
        for title, items in self._menu_spec():
            if title in ("File", "Data Inspection"):
                continue
            mb = ttk.Menubutton(bar, text=title, direction="below")
            menu = self._new_menu(mb)
            self._populate(menu, items)
            mb["menu"] = menu
            mb.pack(side="left", padx=6)

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self.root, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground="white")
        for title, items in self._menu_spec():
            menu = self._new_menu(menubar)
            self._populate(menu, items)
            menubar.add_cascade(label=title, menu=menu)
        helpm = self._new_menu(menubar)
        helpm.add_command(label=f"About {APP_NAME}", command=self.cmd_about)
        menubar.add_cascade(label="Help", menu=helpm)
        self.root.config(menu=menubar)

    def _build_workspace(self) -> None:
        self.notebook = ttk.Notebook(self.main)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._build_data_tab()
        self._build_output_tab()

    def _scrolled_tree(self, parent: tk.Misc, **kw) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, **kw)
        ysb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        return tree

    def _build_data_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Data Sheet")
        paned = ttk.PanedWindow(tab, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        paned.add(left, weight=4)
        self.sheet_note = ttk.Label(left, text="No data loaded.", style="TLabel")
        self.sheet_note.pack(anchor="w", pady=(0, 4))
        self.tree = self._scrolled_tree(left, show="headings", selectmode="browse")
        self.tree.tag_configure("odd", background=STRIPE)

        right = ttk.Frame(paned, style="Card.TFrame", padding=10)
        paned.add(right, weight=2)
        ttk.Label(right, text="Dataset Metadata", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        grid = ttk.Frame(right, style="Card.TFrame")
        grid.pack(fill="x")
        self.meta_vars = {}
        for r, (key, label) in enumerate(
            [
                ("file", "File"),
                ("rows", "Rows"),
                ("cols", "Columns"),
                ("numeric", "Numeric columns"),
                ("missing", "Missing cells"),
                ("complete", "Complete rows"),
            ]
        ):
            ttk.Label(grid, text=label + ":", style="CardBold.TLabel").grid(row=r, column=0, sticky="w", pady=1)
            var = tk.StringVar(value="-")
            ttk.Label(grid, textvariable=var, style="Card.TLabel", wraplength=260).grid(row=r, column=1, sticky="w", padx=(8, 0), pady=1)
            self.meta_vars[key] = var
        ttk.Label(right, text="Columns", style="Section.TLabel").pack(anchor="w", pady=(12, 4))
        holder = ttk.Frame(right, style="Card.TFrame")
        holder.pack(fill="both", expand=True)
        self.meta_tree = self._scrolled_tree(holder, columns=("name", "type", "missing", "pct"), show="headings", selectmode="browse")
        for cid, text, width, anchor in (
            ("name", "Column", 150, "w"),
            ("type", "Type", 78, "w"),
            ("missing", "Missing", 76, "e"),
            ("pct", "Miss %", 72, "e"),
        ):
            self.meta_tree.heading(cid, text=text)
            self.meta_tree.column(cid, width=width, anchor=anchor, stretch=(cid == "name"))
        self.meta_tree.tag_configure("odd", background=STRIPE)
        self.meta_tree.tag_configure("warn", foreground="#9C4A1A")

    def _build_output_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Output Log")
        self.output_tab = tab
        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True)
        self.output = tk.Text(
            frame,
            wrap="none",
            font=(self.mono_family, 10),
            bg=FIELD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=SELECT_BG,
            selectforeground=TEXT,
            inactiveselectbackground=SELECT_BG,
            relief="flat",
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            state="disabled",
            cursor="arrow",
        )
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.output.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=self.output.xview)
        self.output.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.output.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        mono_bold = (self.mono_family, 10, "bold")
        self.output.tag_configure("banner", background=CARD, foreground=ACCENT_DARK, font=mono_bold, spacing1=8, spacing3=4)
        self.output.tag_configure("welcome", foreground=ACCENT_DARK)
        # A disabled Text still supports selecting and copying once it has focus.
        self.output.bind("<Button-1>", lambda _e: self.output.focus_set())

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.main, style="Card.TFrame")
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").pack(side="left")

    def _write_welcome(self) -> None:
        self._append_text(
            f"{APP_NAME}  -  {APP_TAGLINE}\n"
            "Every analysis you run is appended below with a timestamp.\n"
            "Use 'Export Output' to save the log as TXT, CSV or Almond-themed HTML.\n"
            + "-" * 78
            + "\n\n",
            "welcome",
        )

    # ---- small helpers ----------------------------------------------------- #
    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _append_text(self, text: str, tag: str | None = None) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text, tag) if tag else self.output.insert("end", text)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _need_data(self) -> bool:
        if self.df is None:
            messagebox.showinfo(APP_NAME, "Please import a dataset first (File > Open Data...).", parent=self.root)
            return False
        return True

    def _numeric_or_warn(self, minimum: int = 1):
        cols = engine.numeric_columns(self.df)
        if len(cols) < minimum:
            need = "at least two numeric columns" if minimum > 1 else "a numeric column"
            messagebox.showwarning(APP_NAME, f"This analysis needs {need}, but the dataset has {len(cols)}.", parent=self.root)
            return None
        return cols

    def _error(self, message: str) -> None:
        messagebox.showerror(APP_NAME, message, parent=self.root)
        self._set_status("Last action failed: " + message.splitlines()[0][:120])

    # ---- result handling --------------------------------------------------- #
    def _run(self, func, *args, **kwargs) -> bool:
        """Call an engine function on the current dataset and log the result."""
        self._set_status("Running analysis...")
        self.root.update_idletasks()
        try:
            result = func(self.df, *args, **kwargs)
        except Exception as exc:  # engine functions should never raise, but never crash the GUI
            result = engine.error_result(f"Unexpected error: {exc}")
        return self._handle_result(result)

    def _handle_result(self, result: dict, switch_tab: bool = True) -> bool:
        if not result.get("ok"):
            self._error(result.get("error") or "The analysis failed for an unknown reason.")
            return False
        entry = engine.make_log_entry(result)
        self.log_entries.append(entry)
        n = len(self.log_entries)
        self._append_text(f"[#{n}]  {entry['timestamp']}  -  {entry['title']}\n", "banner")
        self._append_text(entry["text"] + "\n\n")
        if switch_tab:
            self.notebook.select(self.output_tab)
        self._set_status(f"Completed: {entry['title']}  ({entry['timestamp']})")
        return True

    # ---- data sheet / metadata views --------------------------------------- #
    @staticmethod
    def _fmt_cell(v) -> str:
        if v is None:
            return ""
        try:
            if pd.isna(v):
                return ""
        except (TypeError, ValueError):
            pass
        if isinstance(v, float):
            return f"{v:.10g}"
        return str(v)

    @staticmethod
    def _col_width(header: str, values: list) -> int:
        chars = max([len(header)] + [len(v) for v in values])
        return int(min(260, max(64, chars * 8 + 18)))

    def _refresh_views(self) -> None:
        df = self.df
        tree = self.tree
        tree.delete(*tree.get_children())
        self.meta_tree.delete(*self.meta_tree.get_children())
        if df is None:
            tree["columns"] = ()
            self.sheet_note.configure(text="No data loaded.")
            for var in self.meta_vars.values():
                var.set("-")
            self.dataset_label.configure(text="No dataset loaded")
            return

        preview = df.head(MAX_PREVIEW_ROWS)
        rows = [[self._fmt_cell(v) for v in r] for r in preview.itertuples(index=False, name=None)]
        ids = ["c0"] + [f"c{i + 1}" for i in range(len(df.columns))]
        tree["columns"] = ids
        tree.heading("c0", text="#")
        tree.column("c0", width=54, anchor="e", stretch=False)
        for i, name in enumerate(df.columns, start=1):
            sample = [r[i - 1] for r in rows[:60]]
            is_num = pd.api.types.is_numeric_dtype(df[name])
            tree.heading(f"c{i}", text=str(name))
            tree.column(f"c{i}", width=self._col_width(str(name), sample), anchor="e" if is_num else "w", stretch=False)
        for n, r in enumerate(rows, start=1):
            tree.insert("", "end", values=[n] + r, tags=("odd",) if n % 2 == 0 else ())
        shown = len(rows)
        total = len(df)
        self.sheet_note.configure(
            text=f"Showing {shown:,} of {total:,} rows" + ("  (preview limited; analyses always use all rows)" if shown < total else "")
        )

        meta = engine.dataset_metadata(df)
        self.meta_vars["file"].set(os.path.basename(self.path) if self.path else "-")
        self.meta_vars["rows"].set(f"{meta['rows']:,}")
        self.meta_vars["cols"].set(f"{meta['columns']:,}")
        self.meta_vars["numeric"].set(f"{meta['numeric_columns']:,}")
        self.meta_vars["missing"].set(f"{meta['missing_cells']:,}  ({meta['missing_pct']:.2f}%)")
        self.meta_vars["complete"].set(f"{meta['complete_rows']:,}")
        cm = engine.column_metadata(df)
        for i, row in enumerate(cm.itertuples(index=False)):
            tags = []
            if i % 2:
                tags.append("odd")
            if row.Missing:
                tags.append("warn")
            self.meta_tree.insert("", "end", values=(row.Column, row.Type, row.Missing, f"{row[5]:.1f}%"), tags=tuple(tags))
        name = os.path.basename(self.path) if self.path else "dataset"
        self.dataset_label.configure(text=f"{name}   |   {meta['rows']:,} rows x {meta['columns']:,} cols")

    # ---- commands: file ----------------------------------------------------- #
    def cmd_open(self) -> None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sample_dir = os.path.join(project_root, "sample_data")
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Import data",
            initialdir=sample_dir if os.path.isdir(sample_dir) else os.getcwd(),
            filetypes=[
                ("Data files", "*.csv *.tsv *.xlsx *.xlsm"),
                ("CSV files", "*.csv"),
                ("TSV files", "*.tsv"),
                ("Excel workbooks", "*.xlsx *.xlsm"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        sheet = None
        if os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm"):
            sheets = engine.excel_sheet_names(path)
            if len(sheets) > 1:
                vals = AnalysisDialog(
                    self.root,
                    "Choose Worksheet",
                    [dict(kind="combo", key="sheet", label="Worksheet:", options=sheets, default=sheets[0], required=True)],
                    prompt="This workbook has several worksheets. Which one should be imported?",
                    ok_text="Import",
                ).show()
                if not vals:
                    return
                sheet = vals["sheet"]
        self._set_status("Loading file...")
        self.root.update_idletasks()
        result = engine.load_file(path, sheet)
        if not result["ok"]:
            self._error(result["error"])
            return
        self.df = result["data"]
        self.path = path
        self._refresh_views()
        self.notebook.select(0)
        # Log the automatic inspection of the freshly imported data.
        self._handle_result(engine.inspect_data(self.df, os.path.basename(path)), switch_tab=False)
        self._set_status(result["message"])

    def cmd_close(self) -> None:
        if self.df is None:
            return
        self.df = None
        self.path = None
        self._refresh_views()
        self._set_status("Dataset closed. The output log was kept.")

    # ---- commands: inspection and descriptives ------------------------------ #
    def cmd_inspect(self) -> None:
        if self._need_data():
            self._handle_result(engine.inspect_data(self.df, os.path.basename(self.path or "")))

    def cmd_univariate(self) -> None:
        if not self._need_data():
            return
        cols = self._numeric_or_warn(1)
        if cols is None:
            return
        vals = AnalysisDialog(
            self.root,
            "Univariate Summary",
            [dict(kind="list", key="columns", label="Numeric variables:", options=cols, default=cols, required=True)],
            prompt="Computes n, missing, mean, SD, variance, minimum and maximum.",
        ).show()
        if vals:
            self._run(engine.univariate_summary, vals["columns"])

    def cmd_distribution(self) -> None:
        if not self._need_data():
            return
        cols = self._numeric_or_warn(1)
        if cols is None:
            return
        vals = AnalysisDialog(
            self.root,
            "Distribution Metrics",
            [
                dict(kind="list", key="columns", label="Numeric variables:", options=cols, default=cols, required=True),
                dict(
                    kind="entry",
                    key="percentiles",
                    label="Custom percentiles:",
                    default="5, 10, 90, 95",
                    hint="Comma-separated values from 0 to 100. Quartiles, median and IQR are always included. Leave blank for none.",
                ),
            ],
            prompt="Quartiles, percentiles, IQR, skewness and kurtosis.",
        ).show()
        if not vals:
            return
        try:
            pcts = engine.parse_number_list(vals["percentiles"])
        except ValueError as exc:
            self._error(f"Invalid percentile list: {exc}")
            return
        self._run(engine.distribution_metrics, vals["columns"], pcts)

    def cmd_frequency(self) -> None:
        if not self._need_data():
            return
        cols = list(self.df.columns)
        vals = AnalysisDialog(
            self.root,
            "Frequency Table",
            [dict(kind="list", key="columns", label="Variables:", options=cols, required=True)],
            prompt="Counts, percent, valid percent and cumulative percent. One table per selected variable.",
        ).show()
        if vals:
            for c in vals["columns"]:
                if not self._run(engine.frequency_table, c):
                    break

    def _two_var_defaults(self, cols: list):
        return cols[0], (cols[1] if len(cols) > 1 else cols[0])

    def cmd_crosstab(self) -> None:
        if not self._need_data():
            return
        cols = list(self.df.columns)
        d1, d2 = self._two_var_defaults(cols)
        vals = AnalysisDialog(
            self.root,
            "Cross-Tabulation",
            [
                dict(kind="combo", key="row", label="Row variable:", options=cols, default=d1, required=True),
                dict(kind="combo", key="col", label="Column variable:", options=cols, default=d2, required=True),
                dict(kind="check", key="row_pct", label="Show row percentages"),
                dict(kind="check", key="col_pct", label="Show column percentages"),
                dict(kind="check", key="tot_pct", label="Show total percentages"),
            ],
            prompt="Two-way contingency table with row and column totals.",
        ).show()
        if vals:
            pcts = [k for k, f in (("row", "row_pct"), ("col", "col_pct"), ("total", "tot_pct")) if vals[f]]
            self._run(engine.cross_tabulation, vals["row"], vals["col"], pcts)

    # ---- commands: hypothesis tests ----------------------------------------- #
    def cmd_chi_independence(self) -> None:
        if not self._need_data():
            return
        cols = list(self.df.columns)
        d1, d2 = self._two_var_defaults(cols)
        vals = AnalysisDialog(
            self.root,
            "Chi-Square Test of Independence",
            [
                dict(kind="combo", key="row", label="Row variable (categorical):", options=cols, default=d1, required=True),
                dict(kind="combo", key="col", label="Column variable (categorical):", options=cols, default=d2, required=True),
            ],
            prompt="Shows observed and expected counts, the chi-square statistic, degrees of freedom and p-value.",
        ).show()
        if vals:
            self._run(engine.chi_square_independence, vals["row"], vals["col"])

    def cmd_chi_gof(self) -> None:
        if not self._need_data():
            return
        cols = list(self.df.columns)
        vals = AnalysisDialog(
            self.root,
            "Chi-Square Goodness-of-Fit",
            [
                dict(kind="combo", key="column", label="Categorical variable:", options=cols, default=cols[0], required=True),
                dict(kind="check", key="custom", label="Specify expected proportions (otherwise all categories are equally likely)"),
            ],
            prompt="Tests whether observed category counts match an expected distribution.",
            ok_text="Next" ,
        ).show()
        if not vals:
            return
        expected = None
        if vals["custom"]:
            cats = engine.categories_of(self.df, vals["column"])
            if len(cats) < 2:
                self._error(f"Column '{vals['column']}' needs at least two categories with data.")
                return
            shown = ", ".join(cats[:30]) + (" ..." if len(cats) > 30 else "")
            v2 = AnalysisDialog(
                self.root,
                "Expected Proportions",
                [
                    dict(kind="info", label=f"{len(cats)} categories, in this order:\n{shown}"),
                    dict(
                        kind="entry",
                        key="expected",
                        label="Expected proportions (one per category):",
                        default=", ".join(["1"] * len(cats)),
                        hint="Comma-separated, same order as above. Proportions, percentages or counts all work; they are normalised to sum to 1.",
                    ),
                ],
            ).show()
            if not v2:
                return
            try:
                expected = engine.parse_number_list(v2["expected"])
            except ValueError as exc:
                self._error(f"Invalid expected proportions: {exc}")
                return
        self._run(engine.chi_square_goodness_of_fit, vals["column"], expected)

    # ---- commands: correlation & regression --------------------------------- #
    def cmd_correlation(self) -> None:
        if not self._need_data():
            return
        cols = self._numeric_or_warn(2)
        if cols is None:
            return
        vals = AnalysisDialog(
            self.root,
            "Correlation Matrix",
            [dict(kind="list", key="columns", label="Numeric variables (select 2 or more):", options=cols, default=cols, required=True)],
            prompt="Pearson r and Spearman rho with two-tailed p-values.",
        ).show()
        if vals:
            self._run(engine.correlation_matrix, vals["columns"])

    def cmd_regression(self) -> None:
        if not self._need_data():
            return
        cols = self._numeric_or_warn(2)
        if cols is None:
            return
        vals = AnalysisDialog(
            self.root,
            "Linear Regression (OLS)",
            [
                dict(kind="combo", key="dep", label="Dependent variable (Y):", options=cols, default=cols[0], required=True),
                dict(kind="list", key="inds", label="Independent variables (X) - one for simple, several for multiple:", options=cols, required=True),
            ],
            prompt="Outputs the model summary (R-squared, adjusted R-squared, F, p), ANOVA table and coefficients table.",
        ).show()
        if vals:
            self._run(engine.linear_regression, vals["dep"], vals["inds"])

    # ---- commands: export --------------------------------------------------- #
    @staticmethod
    def _ensure_ext(path: str) -> str:
        return path if os.path.splitext(path)[1].lower() in (".txt", ".csv", ".html", ".htm") else path + ".txt"

    def _export_dialog_path(self, title: str):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title=title,
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("CSV (tables)", "*.csv"), ("HTML (Almond theme)", "*.html")],
        )
        return self._ensure_ext(path) if path else None

    def _report_export(self, res: dict) -> None:
        if res.get("ok"):
            self._set_status(f"Exported {res['format'].upper()} to {res['path']}")
            messagebox.showinfo(APP_NAME, f"Export complete:\n{res['path']}", parent=self.root)
        else:
            self._error(res.get("error", "Export failed."))

    def cmd_export_log(self) -> None:
        if not self.log_entries:
            messagebox.showinfo(APP_NAME, "The output log is empty. Run an analysis first.", parent=self.root)
            return
        path = self._export_dialog_path("Export Output Log")
        if path:
            self._report_export(engine.export_log(self.log_entries, path))

    def cmd_export_tables(self) -> None:
        items = engine.list_exportable_tables(self.log_entries)
        if not items:
            messagebox.showinfo(APP_NAME, "There are no result tables to export yet.", parent=self.root)
            return
        labels = [lab for _i, _n, lab in items]
        vals = AnalysisDialog(
            self.root,
            "Export Selected Tables",
            [dict(kind="list", key="tables", label="Result tables:", options=labels, height=12, width=78, required=True)],
            prompt="Choose one or more tables. The file type (TXT, CSV or HTML) is picked in the next step.",
            ok_text="Export",
        ).show()
        if not vals:
            return
        lookup = {lab: (i, n) for i, n, lab in items}
        selections = [lookup[lab] for lab in vals["tables"]]
        path = self._export_dialog_path("Export Selected Tables")
        if path:
            self._report_export(engine.export_tables(self.log_entries, selections, path))

    def cmd_clear_log(self) -> None:
        if not self.log_entries:
            return
        if messagebox.askyesno(APP_NAME, "Clear the entire output log? This cannot be undone.", parent=self.root):
            self.log_entries.clear()
            self.output.configure(state="normal")
            self.output.delete("1.0", "end")
            self.output.configure(state="disabled")
            self._write_welcome()
            self._set_status("Output log cleared.")

    def cmd_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}\n{APP_TAGLINE}\n\n"
            "A simple statistics workbench inspired by Excel and SPSS.\n"
            "Built with Python, tkinter, pandas, SciPy and statsmodels.",
            parent=self.root,
        )


def main() -> None:
    try:  # crisp text on high-DPI Windows displays
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - not on Windows / not available
        pass
    root = tk.Tk()
    try:
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "almond_logo2.ico"
        )
        root.iconbitmap(icon_path)
    except Exception:  # noqa: BLE001 - fallback gracefully if icon missing
        pass
    
    AlmondsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
