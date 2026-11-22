"""
stats_engine.py -- A.L.M.O.N.D.S (A Lot of Math On Neat Data Sheets)

Pure statistical computations and file I/O.  This module has ZERO GUI imports,
so everything here can be unit-tested or reused from a script / notebook.

Conventions
-----------
* Every analysis function takes a ``pandas.DataFrame`` plus column names and
  returns a *result dictionary*::

      {
        "ok":       True / False,
        "error":    None or a clear, user-facing message,
        "title":    "Chi-Square Test of Independence: A x B",
        "text":     formatted monospace text (plain-text tables),
        "html":     formatted HTML fragment (tables styled by ALMOND_CSS),
        "tables":   {"Table name": pandas.DataFrame, ...},
        "decimals": {"Table name": 4, ...},      # display precision per table
        "stats":    {...}                        # key numbers for programmatic use
      }

* Public analysis functions never raise: bad input (non-numeric columns,
  empty selections, singular matrices, ...) yields ``ok=False`` and an
  explanatory ``error`` string instead.
"""

from __future__ import annotations

import functools
import html as _html
import io
import os
import re
import textwrap
import warnings
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm

APP_NAME = "A.L.M.O.N.D.S"
APP_TAGLINE = "A Lot of Math On Neat Data Sheets"

MAX_CATEGORIES_FREQ = 200      # max distinct values for a frequency table
MAX_CATEGORIES_CROSS = 50      # max categories per variable in a cross-tab / chi-square

SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm")


# --------------------------------------------------------------------------- #
# Errors and result helpers
# --------------------------------------------------------------------------- #
class AnalysisError(Exception):
    """Raised internally for problems that should be shown to the user as-is."""


def error_result(message: str, title: str = "Error") -> Dict[str, Any]:
    """Build a failed result dictionary."""
    return {
        "ok": False,
        "error": message,
        "title": title,
        "text": f"ERROR: {message}",
        "html": f'<p class="error">{_html.escape(message)}</p>',
        "tables": {},
        "decimals": {},
        "stats": {},
    }


def _safe(func):
    """Decorator: turn any exception into a clean error result (never crash the GUI)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AnalysisError as exc:
            return error_result(str(exc))
        except np.linalg.LinAlgError:
            return error_result(
                "The calculation failed because of a singular matrix. "
                "This usually means two or more variables are perfectly "
                "collinear (one is an exact copy or combination of others)."
            )
        except MemoryError:
            return error_result("Not enough memory to complete this analysis.")
        except Exception as exc:  # noqa: BLE001 - last line of defence for the GUI
            return error_result(f"Unexpected error in {func.__name__}: {exc}")

    return wrapper


# --------------------------------------------------------------------------- #
# Formatting: plain text and HTML tables
# --------------------------------------------------------------------------- #
_NUMLIKE = re.compile(r"^[<>]?-?\d[\d,]*\.?\d*(e[+-]?\d+)?%?$|^\.$|^-?inf$", re.IGNORECASE)


def _is_p_column(name: str) -> bool:
    n = str(name).strip().lower()
    return "p-value" in n or n in ("p", "sig.", "sig")


def format_p(p: float) -> str:
    """Format a p-value the way statistical packages do."""
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "."
    return "<0.0001" if p < 0.0001 else f"{p:.4f}"


def fmt_value(v: Any, column: str = "", decimals: int = 4) -> str:
    """Format a single table cell."""
    if v is None:
        return "."
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if np.isnan(v):
            return "."
        if np.isinf(v):
            return "inf" if v > 0 else "-inf"
        if _is_p_column(column):
            return format_p(v)
        if v != 0 and abs(v) < 10 ** (-decimals):
            return f"{v:.3e}"
        return f"{v:.{decimals}f}"
    try:
        if pd.isna(v):
            return "."
    except (TypeError, ValueError):
        pass
    return str(v)


def _table_cells(df: pd.DataFrame, decimals: int) -> Tuple[List[str], List[List[str]], bool]:
    """Return (headers, rows-of-strings, index_shown) for a DataFrame."""
    show_index = not isinstance(df.index, pd.RangeIndex)
    headers = [str(c) for c in df.columns]
    rows = [
        [fmt_value(v, h, decimals) for v, h in zip(r, headers)]
        for r in df.itertuples(index=False, name=None)
    ]
    if show_index:
        idx_name = "" if df.index.name is None else str(df.index.name)
        headers = [idx_name] + headers
        rows = [[str(i)] + r for i, r in zip(df.index, rows)]
    return headers, rows, show_index


def _column_is_numeric(cells: Sequence[str]) -> bool:
    return all(_NUMLIKE.match(c.strip()) for c in cells if c.strip() != "") and any(
        c.strip() != "" for c in cells
    )


def render_table_text(df: pd.DataFrame, decimals: int = 4) -> str:
    """Render a DataFrame as an SPSS-like monospace table."""
    headers, rows, show_index = _table_cells(df, decimals)
    ncol = len(headers)
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    right = []
    for i in range(ncol):
        if i == 0 and show_index:
            right.append(False)
        else:
            right.append(_column_is_numeric([r[i] for r in rows]))

    def line(cells):
        parts = [c.rjust(widths[i]) if right[i] else c.ljust(widths[i]) for i, c in enumerate(cells)]
        return "  ".join(parts).rstrip()

    rule = "-" * max(len(line(headers)), 1)
    out = [line(headers), rule]
    out.extend(line(r) for r in rows)
    out.append(rule)
    return "\n".join(out)


def render_table_html(df: pd.DataFrame, decimals: int = 4) -> str:
    """Render a DataFrame as an HTML table (styled by ALMOND_CSS)."""
    headers, rows, show_index = _table_cells(df, decimals)
    ncol = len(headers)
    right = []
    for i in range(ncol):
        if i == 0 and show_index:
            right.append(False)
        else:
            right.append(_column_is_numeric([r[i] for r in rows]))
    esc = _html.escape
    parts = ['<table class="almond-table">', "<thead><tr>"]
    for i, h in enumerate(headers):
        parts.append(f'<th class="{"num" if right[i] else "txt"}">{esc(h)}</th>')
    parts.append("</tr></thead><tbody>")
    for r in rows:
        parts.append("<tr>")
        for i, c in enumerate(r):
            tag = "th" if (i == 0 and show_index) else "td"
            cls = "row-label" if tag == "th" else ("num" if right[i] else "txt")
            parts.append(f'<{tag} class="{cls}">{esc(c)}</{tag}>')
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


class _Report:
    """Collects tables and notes, then builds the text + HTML result dictionary."""

    def __init__(self, title: str):
        self.title = title
        self.items: List[Tuple[str, str]] = []
        self.tables: Dict[str, pd.DataFrame] = {}
        self.decimals: Dict[str, int] = {}

    def table(self, name: str, df: pd.DataFrame, decimals: int = 4) -> None:
        base, i = name, 2
        while name in self.tables:
            name = f"{base} ({i})"
            i += 1
        self.tables[name] = df
        self.decimals[name] = decimals
        self.items.append(("table", name))

    def note(self, text: str) -> None:
        self.items.append(("note", text))

    def build(self, stats_dict: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body: List[str] = []
        html_parts: List[str] = [f"<h2>{_html.escape(self.title)}</h2>"]
        width = max(len(self.title), 60)
        rendered: Dict[str, str] = {}
        for kind, key in self.items:
            if kind == "table":
                rendered[key] = render_table_text(self.tables[key], self.decimals[key])
                width = max(width, max(len(l) for l in rendered[key].splitlines()))
        width = min(width, 110)
        body.append("=" * width)
        body.append(self.title)
        body.append("=" * width)
        for kind, key in self.items:
            if kind == "table":
                body.append("")
                body.append(key)
                body.append(rendered[key])
                html_parts.append(f"<h3>{_html.escape(key)}</h3>")
                html_parts.append(
                    '<div class="table-wrap">'
                    + render_table_html(self.tables[key], self.decimals[key])
                    + "</div>"
                )
            else:
                body.append("")
                body.append(
                    textwrap.fill(
                        "Note: " + key, width=max(width, 70), subsequent_indent="      "
                    )
                )
                html_parts.append(f'<p class="note">Note: {_html.escape(key)}</p>')
        return {
            "ok": True,
            "error": None,
            "title": self.title,
            "text": "\n".join(body),
            "html": "\n".join(html_parts),
            "tables": dict(self.tables),
            "decimals": dict(self.decimals),
            "stats": stats_dict or {},
        }


def _kv(items: Iterable[Tuple], decimals: int = 4, label: str = "Statistic") -> pd.DataFrame:
    """Key/value table with pre-formatted values.  Items: (label, value[, 'p'])."""
    labels, values = [], []
    for it in items:
        labels.append(it[0])
        is_p = len(it) > 2 and it[2] == "p"
        values.append(fmt_value(it[1], "p-value" if is_p else "", decimals))
    df = pd.DataFrame({"Value": values}, index=pd.Index(labels, name=label))
    return df


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #
def _check_df(df: Any) -> None:
    if df is None or not isinstance(df, pd.DataFrame):
        raise AnalysisError("No dataset is loaded. Import a CSV, TSV or Excel file first.")
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise AnalysisError("The dataset is empty (no rows or no columns).")


def _check_cols(df: pd.DataFrame, cols: Any, label: str = "variable") -> List[str]:
    if cols is None:
        cols = []
    if isinstance(cols, str):
        cols = [cols]
    cols = list(dict.fromkeys(cols))
    if not cols:
        raise AnalysisError(f"No {label} selected. Please select at least one {label}.")
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise AnalysisError(f"Column(s) not found in the dataset: {', '.join(map(str, missing))}.")
    return cols


def _is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def _numeric_frame(df: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    bad = [c for c in cols if not _is_numeric(df[c])]
    if bad:
        raise AnalysisError(
            "These columns are not numeric and cannot be used here: "
            + ", ".join(f"'{c}'" for c in bad)
            + ". Choose numeric columns (integers or decimals)."
        )
    return df[list(cols)].astype(float)


def _labelize(s: pd.Series) -> Tuple[pd.Series, List[str]]:
    """Drop missing values; return string labels and the sorted category order."""
    s = s.dropna()
    if (
        pd.api.types.is_float_dtype(s)
        and len(s)
        and bool(np.isfinite(s).all())
        and bool((s % 1 == 0).all())
        and bool((s.abs() < 1e15).all())
    ):
        s = s.astype("int64")
    uniq = list(pd.unique(s))
    try:
        uniq_sorted = sorted(uniq)
    except TypeError:
        uniq_sorted = sorted(uniq, key=str)
    order = list(dict.fromkeys(str(u) for u in uniq_sorted))
    return s.astype(str), order


def _col_label_list(cols: Sequence[str]) -> str:
    return ", ".join(f"'{c}'" for c in cols)


# --------------------------------------------------------------------------- #
# 1. Data import and inspection
# --------------------------------------------------------------------------- #
def excel_sheet_names(path: str) -> List[str]:
    """Return the sheet names of an Excel workbook ([] if unreadable)."""
    try:
        with pd.ExcelFile(path, engine="openpyxl") as xf:
            return list(xf.sheet_names)
    except Exception:  # noqa: BLE001
        return []


def _clean_loaded_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    # Drop completely empty "Unnamed" columns that spreadsheets often produce.
    drop = [c for c in df.columns if c.startswith("Unnamed:") and df[c].isna().all()]
    df = df.drop(columns=drop)
    # Strip whitespace in text cells and turn blank strings into missing values.
    for c in df.columns:
        s = df[c]
        if s.dtype == object or pd.api.types.is_string_dtype(s):
            df[c] = s.map(lambda v: (v.strip() or np.nan) if isinstance(v, str) else v)
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def load_file(path: str, sheet: Any = None) -> Dict[str, Any]:
    """
    Import a .csv, .tsv, .txt or .xlsx file.

    Returns ``{"ok", "error", "data" (DataFrame), "message"}``.
    """
    try:
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": f"File not found: {path}", "data": None}
        ext = os.path.splitext(path)[1].lower()
        df = None
        if ext in (".csv", ".tsv", ".txt"):
            last_exc: Optional[Exception] = None
            for enc in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    if ext == ".csv":
                        df = pd.read_csv(path, encoding=enc)
                    elif ext == ".tsv":
                        df = pd.read_csv(path, sep="\t", encoding=enc)
                    else:  # .txt: sniff the delimiter
                        df = pd.read_csv(path, sep=None, engine="python", encoding=enc)
                    break
                except UnicodeDecodeError as exc:
                    last_exc = exc
            if df is None:
                raise ValueError(f"Could not decode the file ({last_exc}).")
        elif ext in (".xlsx", ".xlsm"):
            df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, engine="openpyxl")
        elif ext == ".xls":
            return {
                "ok": False,
                "error": "Legacy .xls files are not supported. Please save the workbook as .xlsx and try again.",
                "data": None,
            }
        else:
            return {
                "ok": False,
                "error": f"Unsupported file type '{ext}'. Supported types: .csv, .tsv, .xlsx.",
                "data": None,
            }
        df = _clean_loaded_frame(df)
        if df.shape[1] == 0 or df.shape[0] == 0:
            return {"ok": False, "error": "The file contains no data rows or no columns.", "data": None}
        return {
            "ok": True,
            "error": None,
            "data": df,
            "message": f"Loaded {df.shape[0]:,} rows x {df.shape[1]:,} columns from {os.path.basename(path)}",
        }
    except pd.errors.EmptyDataError:
        return {"ok": False, "error": "The file is empty.", "data": None}
    except pd.errors.ParserError as exc:
        return {"ok": False, "error": f"The file could not be parsed (is it really a delimited text file?): {exc}", "data": None}
    except PermissionError:
        return {"ok": False, "error": "Permission denied. Close the file in other programs and try again.", "data": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not read the file: {exc}", "data": None}


def inferred_type(s: pd.Series) -> str:
    """Human-friendly inferred data type of a column."""
    if pd.api.types.is_bool_dtype(s):
        return "Boolean"
    if pd.api.types.is_integer_dtype(s):
        return "Integer"
    if pd.api.types.is_float_dtype(s):
        return "Decimal"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "Datetime"
    if isinstance(s.dtype, pd.CategoricalDtype):
        return "Categorical"
    return "Text"


def numeric_columns(df: pd.DataFrame) -> List[str]:
    """Names of numeric (non-boolean) columns."""
    return [c for c in df.columns if _is_numeric(df[c])]


def column_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Per-column type / missing-value table (also used by the GUI side panel)."""
    n = len(df)
    rows = []
    for c in df.columns:
        s = df[c]
        miss = int(s.isna().sum())
        rows.append(
            {
                "Column": str(c),
                "Type": inferred_type(s),
                "Kind": "Numeric" if _is_numeric(s) else "Categorical",
                "Non-Missing": n - miss,
                "Missing": miss,
                "Missing %": (100.0 * miss / n) if n else np.nan,
                "Unique": int(s.nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows)


def dataset_metadata(df: pd.DataFrame) -> Dict[str, Any]:
    """Dataset-level summary numbers."""
    n_rows, n_cols = df.shape
    total = n_rows * n_cols
    miss = int(df.isna().sum().sum())
    return {
        "rows": n_rows,
        "columns": n_cols,
        "cells": total,
        "missing_cells": miss,
        "missing_pct": (100.0 * miss / total) if total else 0.0,
        "complete_rows": int((~df.isna().any(axis=1)).sum()),
        "duplicate_rows": int(df.duplicated().sum()),
        "numeric_columns": len(numeric_columns(df)),
    }


@_safe
def inspect_data(df: pd.DataFrame, source_name: str = "") -> Dict[str, Any]:
    """Columns, inferred types, row/column counts and missing values."""
    _check_df(df)
    meta = dataset_metadata(df)
    title = "Data Inspection" + (f": {source_name}" if source_name else "")
    rep = _Report(title)
    rep.table(
        "Dataset Overview",
        _kv(
            [
                ("Rows (cases)", meta["rows"]),
                ("Columns (variables)", meta["columns"]),
                ("Numeric columns", meta["numeric_columns"]),
                ("Total cells", meta["cells"]),
                ("Missing cells", meta["missing_cells"]),
                ("Missing cells (%)", f"{meta['missing_pct']:.2f}%"),
                ("Complete rows", meta["complete_rows"]),
                ("Duplicate rows", meta["duplicate_rows"]),
            ],
            label="Property",
        ),
    )
    cm = column_metadata(df).set_index("Column")
    cm.index.name = "Column"
    rep.table("Column Information", cm, decimals=2)
    cols_with_missing = [c for c in df.columns if df[c].isna().any()]
    if cols_with_missing:
        rep.note(f"{len(cols_with_missing)} column(s) contain missing values; analyses use pairwise or listwise deletion as described in each output.")
    else:
        rep.note("No missing values were found.")
    return rep.build({"metadata": meta})


# --------------------------------------------------------------------------- #
# 2. Descriptive statistics
# --------------------------------------------------------------------------- #
def parse_number_list(text: str) -> List[float]:
    """Parse '5, 10 90;95' into [5.0, 10.0, 90.0, 95.0].  Raises ValueError."""
    if text is None or not str(text).strip():
        return []
    out = []
    for tok in re.split(r"[,\s;]+", str(text).strip()):
        if tok == "":
            continue
        try:
            out.append(float(tok.rstrip("%")))
        except ValueError:
            raise ValueError(f"'{tok}' is not a number.") from None
    return out


def _fmt_pct_label(p: float) -> str:
    return f"P{p:g}"


@_safe
def univariate_summary(df: pd.DataFrame, columns: Sequence[str]) -> Dict[str, Any]:
    """n, missing, mean, SD, variance, min, max for each selected numeric column."""
    _check_df(df)
    cols = _check_cols(df, columns, "column")
    X = _numeric_frame(df, cols)
    rows = {}
    for c in cols:
        s = X[c].dropna()
        rows[c] = {
            "N": int(len(s)),
            "Missing": int(len(X) - len(s)),
            "Mean": s.mean(),
            "Std. Dev.": s.std(ddof=1),
            "Variance": s.var(ddof=1),
            "Min": s.min(),
            "Max": s.max(),
        }
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "Variable"
    rep = _Report("Descriptive Statistics: Univariate Summary")
    rep.table("Univariate Summary", table)
    rep.note("Standard deviation and variance use the sample (n - 1) denominator. Missing values are excluded for each variable separately.")
    return rep.build({"summary": table})


@_safe
def distribution_metrics(
    df: pd.DataFrame, columns: Sequence[str], percentiles: Optional[Sequence[float]] = None
) -> Dict[str, Any]:
    """Quartiles, median, IQR, custom percentiles, skewness and kurtosis."""
    _check_df(df)
    cols = _check_cols(df, columns, "column")
    X = _numeric_frame(df, cols)
    pcts = list(percentiles or [])
    for p in pcts:
        if not (0 <= p <= 100):
            raise AnalysisError(f"Percentile {p:g} is out of range. Percentiles must be between 0 and 100.")
    pcts = list(dict.fromkeys(pcts))
    rows = {}
    for c in cols:
        s = X[c].dropna()
        n = len(s)
        q = (lambda p: s.quantile(p / 100.0)) if n else (lambda p: np.nan)
        row = {
            "N": n,
            "Q1 (25th)": q(25),
            "Median (Q2)": q(50),
            "Q3 (75th)": q(75),
            "IQR": (q(75) - q(25)) if n else np.nan,
        }
        for p in pcts:
            row[_fmt_pct_label(p)] = q(p)
        row["Skewness"] = s.skew() if n >= 3 else np.nan
        row["Kurtosis"] = s.kurt() if n >= 4 else np.nan
        rows[c] = row
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "Variable"
    rep = _Report("Descriptive Statistics: Distribution Metrics")
    rep.table("Distribution Metrics", table)
    rep.note(
        "Percentiles use linear interpolation. Skewness is the adjusted Fisher-Pearson coefficient (needs n >= 3); "
        "kurtosis is EXCESS kurtosis (normal = 0, needs n >= 4)."
    )
    return rep.build({"metrics": table})


@_safe
def frequency_table(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    """Counts, percent, valid percent and cumulative percent for one column."""
    _check_df(df)
    col = _check_cols(df, column, "column")[0]
    s = df[col]
    total = len(s)
    labels, order = _labelize(s)
    n_valid = len(labels)
    if n_valid == 0:
        raise AnalysisError(f"Column '{col}' has no valid (non-missing) values.")
    if len(order) > MAX_CATEGORIES_FREQ:
        raise AnalysisError(
            f"Column '{col}' has {len(order):,} distinct values (limit {MAX_CATEGORIES_FREQ}). "
            "Frequency tables are meant for categorical or low-cardinality columns."
        )
    counts = labels.value_counts().reindex(order).fillna(0).astype(int)
    valid_pct = counts / n_valid * 100.0
    table = pd.DataFrame(
        {
            "Frequency": counts.values,
            "Percent": counts.values / total * 100.0,
            "Valid Percent": valid_pct.values,
            "Cumulative Percent": valid_pct.cumsum().values,
        },
        index=pd.Index(order, name=col),
    )
    n_missing = total - n_valid
    if n_missing:
        table.loc["(Missing)"] = [n_missing, n_missing / total * 100.0, np.nan, np.nan]
    table.loc["Total"] = [total, 100.0, 100.0 if n_valid else np.nan, np.nan]
    table["Frequency"] = table["Frequency"].astype(int)
    rep = _Report(f"Frequency Table: {col}")
    rep.table("Frequencies", table, decimals=2)
    rep.note(f"Valid N = {n_valid:,}; missing = {n_missing:,}. 'Percent' uses all rows; 'Valid Percent' excludes missing values.")
    return rep.build({"table": table, "n_valid": n_valid, "n_missing": n_missing})


def _with_margins(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Total"] = out.sum(axis=1)
    out.loc["Total"] = out.sum(axis=0)
    return out


def _contingency(df: pd.DataFrame, row_var: str, col_var: str) -> Tuple[pd.DataFrame, int]:
    """Observed counts (plain string index/columns), plus number of rows dropped for missing data."""
    if row_var == col_var:
        raise AnalysisError("Please choose two different variables for the row and column.")
    sub = df[[row_var, col_var]].dropna().reset_index(drop=True)
    dropped = len(df) - len(sub)
    if len(sub) == 0:
        raise AnalysisError("No rows have valid values in both selected variables.")
    a, order_a = _labelize(sub[row_var])
    b, order_b = _labelize(sub[col_var])
    for name, order in ((row_var, order_a), (col_var, order_b)):
        if len(order) > MAX_CATEGORIES_CROSS:
            raise AnalysisError(
                f"Column '{name}' has {len(order)} distinct values (limit {MAX_CATEGORIES_CROSS}). "
                "Choose a categorical column with fewer categories."
            )
    obs = pd.crosstab(a, b).reindex(index=order_a, columns=order_b, fill_value=0)
    obs.index = pd.Index([str(i) for i in obs.index], name=row_var)
    obs.columns = pd.Index([str(c) for c in obs.columns], name=None)
    return obs.astype(int), dropped


@_safe
def cross_tabulation(
    df: pd.DataFrame,
    row_var: str,
    col_var: str,
    percentages: Sequence[str] = (),
) -> Dict[str, Any]:
    """
    2-way contingency table with margins.

    ``percentages`` may contain any of ``"row"``, ``"col"``, ``"total"``.
    """
    _check_df(df)
    row_var = _check_cols(df, row_var, "row variable")[0]
    col_var = _check_cols(df, col_var, "column variable")[0]
    obs, dropped = _contingency(df, row_var, col_var)
    counts = _with_margins(obs)
    rep = _Report(f"Cross-Tabulation: {row_var} x {col_var}")
    rep.table(f"Counts (rows: {row_var}, columns: {col_var})", counts)
    pcts = set(percentages or [])
    if "row" in pcts:
        t = counts.div(counts["Total"].replace(0, np.nan), axis=0) * 100.0
        rep.table("Row Percentages (%)", t, decimals=1)
    if "col" in pcts:
        t = counts.div(counts.loc["Total"].replace(0, np.nan), axis=1) * 100.0
        rep.table("Column Percentages (%)", t, decimals=1)
    if "total" in pcts:
        t = counts / float(counts.loc["Total", "Total"]) * 100.0
        rep.table("Total Percentages (%)", t, decimals=1)
    rep.note(f"Valid N = {int(counts.loc['Total', 'Total']):,}; {dropped:,} row(s) excluded because of missing values.")
    return rep.build({"observed": obs, "n": int(obs.values.sum()), "dropped": dropped})


# --------------------------------------------------------------------------- #
# 3. Hypothesis testing: chi-square
# --------------------------------------------------------------------------- #
def categories_of(df: pd.DataFrame, column: str) -> List[str]:
    """Sorted category labels of a column (used by the GUI for goodness-of-fit)."""
    if df is None or column not in df.columns:
        return []
    return _labelize(df[column])[1]


@_safe
def chi_square_independence(df: pd.DataFrame, row_var: str, col_var: str) -> Dict[str, Any]:
    """Chi-square test of independence for two categorical columns."""
    _check_df(df)
    row_var = _check_cols(df, row_var, "row variable")[0]
    col_var = _check_cols(df, col_var, "column variable")[0]
    obs, dropped = _contingency(df, row_var, col_var)
    r, c = obs.shape
    if r < 2 or c < 2:
        raise AnalysisError(
            f"A chi-square test needs at least 2 categories in each variable (found {r} x {c}). "
            "Choose variables that vary."
        )
    n = int(obs.values.sum())
    chi2, p, dof, expected = stats.chi2_contingency(obs.values, correction=False)
    tests = [("Pearson Chi-Square", chi2, dof, p)]
    lr = stats.chi2_contingency(obs.values, correction=False, lambda_="log-likelihood")
    tests.append(("Likelihood Ratio", lr[0], lr[2], lr[1]))
    if (r, c) == (2, 2):
        yates = stats.chi2_contingency(obs.values, correction=True)
        tests.append(("Continuity Correction (Yates)", yates[0], yates[2], yates[1]))
    test_df = pd.DataFrame(
        {"Value": [t[1] for t in tests], "df": [int(t[2]) for t in tests], "p-value": [t[3] for t in tests]},
        index=pd.Index([t[0] for t in tests], name="Test"),
    )
    exp_df = pd.DataFrame(expected, index=obs.index, columns=obs.columns)
    resid = (obs.values - expected) / np.sqrt(expected)
    resid_df = pd.DataFrame(resid, index=obs.index, columns=obs.columns)

    k = min(r - 1, c - 1)
    cramers_v = float(np.sqrt(chi2 / (n * k))) if n * k > 0 else np.nan
    contingency_c = float(np.sqrt(chi2 / (chi2 + n)))
    measures = [("Cramer's V", cramers_v), ("Contingency Coefficient", contingency_c)]
    if (r, c) == (2, 2):
        measures.insert(0, ("Phi", float(np.sqrt(chi2 / n))))
    measure_df = pd.DataFrame({"Value": [m[1] for m in measures]}, index=pd.Index([m[0] for m in measures], name="Measure"))

    low = int((expected < 5).sum())
    low_pct = 100.0 * low / expected.size

    rep = _Report(f"Chi-Square Test of Independence: {row_var} x {col_var}")
    rep.table("Observed Counts", _with_margins(obs))
    rep.table("Expected Counts (under independence)", _with_margins(exp_df), decimals=2)
    rep.table("Standardized Residuals (Observed - Expected) / sqrt(Expected)", resid_df, decimals=2)
    rep.table("Chi-Square Tests", test_df)
    rep.table("Strength of Association", measure_df)
    rep.note(f"N of valid cases = {n:,}; {dropped:,} row(s) excluded because of missing values. Pearson chi-square is uncorrected.")
    if low:
        rep.note(
            f"{low} cell(s) ({low_pct:.1f}%) have an expected count below 5 (minimum expected = {expected.min():.2f}). "
            "The chi-square approximation may be unreliable; consider combining categories."
        )
    else:
        rep.note("All expected counts are at least 5, so the chi-square approximation is appropriate.")
    rep.note(
        ("Result: significant association at the 0.05 level." if p < 0.05 else "Result: no significant association at the 0.05 level.")
    )
    return rep.build(
        {
            "chi2": float(chi2),
            "df": int(dof),
            "p_value": float(p),
            "n": n,
            "cramers_v": cramers_v,
            "observed": obs,
            "expected": exp_df,
            "cells_expected_lt_5": low,
        }
    )


@_safe
def chi_square_goodness_of_fit(
    df: pd.DataFrame, column: str, expected: Any = None
) -> Dict[str, Any]:
    """
    Chi-square goodness-of-fit test for one categorical column.

    ``expected`` may be None (equal proportions), a list of weights in sorted
    category order, or a dict ``{category_label: weight}``.  Weights are
    normalised, so proportions, percentages or counts are all accepted.
    """
    _check_df(df)
    col = _check_cols(df, column, "column")[0]
    labels, order = _labelize(df[col])
    n = len(labels)
    dropped = len(df) - n
    if n == 0:
        raise AnalysisError(f"Column '{col}' has no valid (non-missing) values.")
    k = len(order)
    if k < 2:
        raise AnalysisError(f"Column '{col}' has only one category; a goodness-of-fit test needs at least 2.")
    if k > 100:
        raise AnalysisError(f"Column '{col}' has {k} categories (limit 100). Choose a categorical column.")
    observed = labels.value_counts().reindex(order).fillna(0).astype(int)

    if expected is None or (hasattr(expected, "__len__") and len(expected) == 0):
        weights = np.ones(k)
        mode = "equal proportions across all categories"
    else:
        if isinstance(expected, dict):
            missing = [cat for cat in order if cat not in {str(x) for x in expected}]
            if missing:
                raise AnalysisError("Expected values are missing for category: " + ", ".join(missing))
            lookup = {str(kk): vv for kk, vv in expected.items()}
            weights = np.array([lookup[cat] for cat in order], dtype=float)
        else:
            if len(expected) != k:
                raise AnalysisError(
                    f"Expected {k} values (one per category, in this order: {', '.join(order)}), but {len(expected)} were given."
                )
            weights = np.array(list(expected), dtype=float)
        if not np.all(np.isfinite(weights)) or np.any(weights <= 0):
            raise AnalysisError("Expected proportions must be positive numbers.")
        mode = "user-specified proportions (normalised to sum to 1)"
    props = weights / weights.sum()
    exp_counts = props * n
    chi2, p = stats.chisquare(observed.values.astype(float), exp_counts)
    dof = k - 1

    table = pd.DataFrame(
        {
            "Observed N": observed.values,
            "Expected Prop.": props,
            "Expected N": exp_counts,
            "Residual": observed.values - exp_counts,
            "Std. Residual": (observed.values - exp_counts) / np.sqrt(exp_counts),
        },
        index=pd.Index(order, name=col),
    )
    table.loc["Total"] = [n, props.sum(), exp_counts.sum(), 0.0, np.nan]
    table["Observed N"] = table["Observed N"].astype(int)
    test_df = pd.DataFrame(
        {"Value": [chi2], "df": [dof], "p-value": [p]}, index=pd.Index(["Pearson Chi-Square"], name="Test")
    )
    low = int((exp_counts < 5).sum())
    rep = _Report(f"Chi-Square Goodness-of-Fit Test: {col}")
    rep.table("Observed vs. Expected", table, decimals=3)
    rep.table("Test Statistics", test_df)
    rep.note(f"Null hypothesis: the data follow {mode}. N = {n:,}; {dropped:,} row(s) excluded because of missing values.")
    if low:
        rep.note(f"{low} category(ies) have an expected count below 5; the chi-square approximation may be unreliable.")
    rep.note("Result: observed counts differ significantly from expected at the 0.05 level." if p < 0.05 else "Result: no significant difference from expected counts at the 0.05 level.")
    return rep.build({"chi2": float(chi2), "df": dof, "p_value": float(p), "n": n, "observed": observed, "expected": exp_counts})


# --------------------------------------------------------------------------- #
# 4. Correlation and regression
# --------------------------------------------------------------------------- #
@_safe
def correlation_matrix(df: pd.DataFrame, columns: Sequence[str]) -> Dict[str, Any]:
    """Pairwise Pearson r and Spearman rho (with two-tailed p-values)."""
    _check_df(df)
    cols = _check_cols(df, columns, "column")
    if len(cols) < 2:
        raise AnalysisError("Select at least two numeric variables to compute a correlation matrix.")
    X = _numeric_frame(df, cols)
    k = len(cols)
    pear = pd.DataFrame(np.eye(k), index=cols, columns=cols)
    spear = pd.DataFrame(np.eye(k), index=cols, columns=cols)
    pairs = []
    skipped = []
    for i in range(k):
        for j in range(i + 1, k):
            a, b = cols[i], cols[j]
            pair = X[[a, b]].dropna()
            n = len(pair)
            r = pr = rho = ps = np.nan
            if n < 3:
                skipped.append(f"{a} / {b} (only {n} complete pair(s))")
            elif pair[a].nunique() < 2 or pair[b].nunique() < 2:
                skipped.append(f"{a} / {b} (one variable is constant)")
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    r, pr = stats.pearsonr(pair[a].values, pair[b].values)
                    rho, ps = stats.spearmanr(pair[a].values, pair[b].values)
            pear.iloc[i, j] = pear.iloc[j, i] = r
            spear.iloc[i, j] = spear.iloc[j, i] = rho
            pairs.append(
                {
                    "Variable 1": a,
                    "Variable 2": b,
                    "N": n,
                    "Pearson r": r,
                    "p-value (Pearson)": pr,
                    "Spearman rho": rho,
                    "p-value (Spearman)": ps,
                }
            )
    pear.index.name = spear.index.name = "Variable"
    pair_df = pd.DataFrame(pairs)
    rep = _Report("Correlation Matrix: Pearson r and Spearman rho")
    rep.table("Pearson r", pear, decimals=3)
    rep.table("Spearman rho", spear, decimals=3)
    rep.table("Pairwise Detail (two-tailed p-values)", pair_df, decimals=4)
    rep.note("Correlations use pairwise deletion of missing values (N is shown for each pair). Spearman rho is computed on ranks.")
    if skipped:
        rep.note("Could not compute: " + "; ".join(skipped) + ".")
    return rep.build({"pearson": pear, "spearman": spear, "pairs": pair_df})


@_safe
def linear_regression(
    df: pd.DataFrame,
    dependent: str,
    independents: Sequence[str],
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """Simple or multiple linear regression (OLS) using statsmodels."""
    _check_df(df)
    if not dependent:
        raise AnalysisError("No dependent variable selected.")
    dep = _check_cols(df, dependent, "dependent variable")[0]
    inds = _check_cols(df, independents, "independent variable")
    if dep in inds:
        raise AnalysisError(f"'{dep}' cannot be both the dependent variable and an independent variable.")
    data = _numeric_frame(df, [dep] + inds).dropna()
    n, k = len(data), len(inds)
    dropped = len(df) - n
    if n < k + 2:
        raise AnalysisError(
            f"Not enough complete observations: {n} row(s) have no missing values, but a model with "
            f"{k} predictor(s) needs at least {k + 2}."
        )
    if data[dep].nunique() < 2:
        raise AnalysisError(f"The dependent variable '{dep}' is constant in the complete cases; nothing to explain.")
    constant = [c for c in inds if data[c].nunique() < 2]
    if constant:
        raise AnalysisError("These predictors are constant in the complete cases: " + _col_label_list(constant) + ". Remove them and try again.")

    X = sm.add_constant(data[inds], has_constant="add")
    y = data[dep]
    if np.linalg.matrix_rank(X.values) < X.shape[1]:
        raise AnalysisError(
            "The predictors are perfectly collinear (singular design matrix): at least one predictor is an exact "
            "combination of the others. Remove redundant variables and try again."
        )
    model = sm.OLS(y, X).fit()

    def f(x):
        return float(np.asarray(x).reshape(-1)[0])

    with np.errstate(all="ignore"):
        r2 = f(model.rsquared)
        adj = f(model.rsquared_adj)
        fval = f(model.fvalue)
        fp = f(model.f_pvalue)
        se_est = float(np.sqrt(model.mse_resid))
        cond = float(np.linalg.cond(X.values))
    conf_pct = int(round(confidence * 100))

    summary = _kv(
        [
            ("Multiple R", float(np.sqrt(max(r2, 0.0)))),
            ("R Square", r2),
            ("Adjusted R Square", adj),
            ("Std. Error of the Estimate", se_est),
            ("F statistic", fval),
            ("df (model, residual)", f"{int(model.df_model)}, {int(model.df_resid)}"),
            ("p-value (F)", fp, "p"),
            ("N (complete cases)", n),
            ("AIC", float(model.aic)),
            ("BIC", float(model.bic)),
        ],
        label="Model Summary",
    )

    anova = pd.DataFrame(
        {
            "Sum of Squares": [model.ess, model.ssr, model.centered_tss],
            "df": [int(model.df_model), int(model.df_resid), n - 1],
            "Mean Square": [model.mse_model, model.mse_resid, np.nan],
            "F": [fval, np.nan, np.nan],
            "p-value": [fp, np.nan, np.nan],
        },
        index=pd.Index(["Regression", "Residual", "Total"], name="Source"),
    )

    ci = model.conf_int(alpha=1 - confidence)
    names = ["(Intercept)"] + inds
    sd_y = data[dep].std(ddof=1)
    betas = [np.nan] + [model.params[c] * data[c].std(ddof=1) / sd_y for c in inds]
    coef = pd.DataFrame(
        {
            "Estimate": model.params.values,
            "Std. Error": model.bse.values,
            "Std. Beta": betas,
            "t": model.tvalues.values,
            "p-value": model.pvalues.values,
            f"{conf_pct}% CI Lower": ci.iloc[:, 0].values,
            f"{conf_pct}% CI Upper": ci.iloc[:, 1].values,
        },
        index=pd.Index(names, name="Term"),
    )

    kind = "Simple" if k == 1 else "Multiple"
    rep = _Report(f"{kind} Linear Regression (OLS): {dep} ~ {' + '.join(inds)}")
    rep.table("Model Summary", summary)
    rep.table("ANOVA", anova)
    rep.table("Coefficients", coef)
    equation = f"{dep} = {model.params['const']:.4f}" + "".join(
        f" {'+' if model.params[c] >= 0 else '-'} {abs(model.params[c]):.4f}*{c}" for c in inds
    )
    rep.note("Fitted equation: " + equation)
    rep.note(f"N = {n:,} complete cases used; {dropped:,} row(s) excluded because of missing values (listwise deletion).")
    if cond > 1e8:
        rep.note(f"The design matrix condition number is very large ({cond:.2e}); predictors may be nearly collinear and estimates unstable.")
    rep.note("Std. Beta = coefficient in standard-deviation units. p-values are two-tailed.")
    return rep.build(
        {
            "r_squared": r2,
            "adj_r_squared": adj,
            "f": fval,
            "f_pvalue": fp,
            "n": n,
            "params": {nm: float(v) for nm, v in zip(names, model.params.values)},
            "coefficients": coef,
            "anova": anova,
        }
    )


# --------------------------------------------------------------------------- #
# 5. Output log and export
# --------------------------------------------------------------------------- #
ALMOND_CSS = """
:root { --bg:#FAF5EF; --card:#F2E8DC; --text:#3B2F2F; --accent:#A67B5B; --border:#C8A883; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--text); margin: 0; padding: 24px;
       font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; line-height: 1.45; }
.page { max-width: 1100px; margin: 0 auto; border: 6px solid var(--border); border-radius: 14px;
        background: var(--bg); padding: 24px 28px; }
header.banner { border-bottom: 3px solid var(--accent); margin-bottom: 18px; padding-bottom: 8px; }
header.banner h1 { margin: 0; letter-spacing: 3px; color: var(--accent); }
header.banner p { margin: 2px 0 0; font-size: 0.9em; opacity: .85; }
section.result { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
                 padding: 14px 18px; margin: 18px 0; }
section.result .stamp { font-size: 0.8em; color: var(--accent); font-weight: 600; letter-spacing: .5px; }
section.result h2 { margin: 4px 0 8px; font-size: 1.25em; }
section.result h3 { margin: 16px 0 6px; font-size: 1em; color: var(--accent); }
.table-wrap { overflow-x: auto; }
table.almond-table { border-collapse: collapse; font-family: Consolas, "DejaVu Sans Mono", Menlo, monospace;
                     font-size: 0.88em; background: #FFFDFA; }
table.almond-table th, table.almond-table td { padding: 4px 12px; border-bottom: 1px solid #E4D3C0; }
table.almond-table thead th { background: var(--accent); color: #fff; text-align: left; }
table.almond-table th.num, table.almond-table td.num { text-align: right; }
table.almond-table th.row-label { background: #EBDCCB; text-align: left; font-weight: 600; }
table.almond-table tbody tr:hover td { background: #F7EDE1; }
p.note { font-size: 0.85em; margin: 8px 0 0; opacity: .9; }
p.error { color: #8B1E1E; font-weight: 600; }
footer { text-align: center; font-size: .8em; opacity: .7; margin-top: 20px; }
""".strip()


def make_log_entry(result: Dict[str, Any], timestamp: Optional[str] = None) -> Dict[str, Any]:
    """Wrap an analysis result with a timestamp so it can be appended to the output log."""
    return {
        "timestamp": timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "title": result.get("title", "Analysis"),
        "text": result.get("text", ""),
        "html": result.get("html", ""),
        "tables": dict(result.get("tables", {})),
        "decimals": dict(result.get("decimals", {})),
    }


def log_to_text(entries: Sequence[Dict[str, Any]]) -> str:
    """Render log entries as one plain-text document."""
    out = [f"{APP_NAME} - {APP_TAGLINE}", f"Output log exported {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    for i, e in enumerate(entries, 1):
        out.append(f"[#{i}] {e['timestamp']}")
        out.append(e["text"])
        out.append("")
    return "\n".join(out)


def log_to_html(entries: Sequence[Dict[str, Any]]) -> str:
    """Render log entries as a standalone, Almond-themed HTML page."""
    esc = _html.escape
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{esc(APP_NAME)} Output Log</title>",
        f"<style>{ALMOND_CSS}</style></head><body><div class=\"page\">",
        f'<header class="banner"><h1>{esc(APP_NAME)}</h1><p>{esc(APP_TAGLINE)} &mdash; Output Log</p></header>',
    ]
    for i, e in enumerate(entries, 1):
        parts.append(
            f'<section class="result"><div class="stamp">#{i} &middot; {esc(e["timestamp"])}</div>{e["html"]}</section>'
        )
    parts.append(f"<footer>Exported {datetime.now():%Y-%m-%d %H:%M:%S} by {esc(APP_NAME)}</footer></div></body></html>")
    return "\n".join(parts)


def log_to_csv(entries: Sequence[Dict[str, Any]]) -> str:
    """Every table of every entry as CSV blocks separated by comment lines."""
    buf = io.StringIO()
    for i, e in enumerate(entries, 1):
        for name, tdf in e.get("tables", {}).items():
            buf.write(f'# [#{i}] {e["timestamp"]} | {e["title"]} | {name}\n')
            tdf.to_csv(buf, index=not isinstance(tdf.index, pd.RangeIndex), lineterminator="\n")
            buf.write("\n")
    return buf.getvalue()


def _infer_format(path: str, fmt: Optional[str]) -> str:
    fmt = (fmt or os.path.splitext(path)[1].lstrip(".")).lower()
    if fmt in ("txt", "text"):
        return "txt"
    if fmt == "csv":
        return "csv"
    if fmt in ("html", "htm"):
        return "html"
    raise AnalysisError("Unsupported export format. Use a .txt, .csv or .html file name.")


def _write_entries(entries: Sequence[Dict[str, Any]], path: str, fmt: Optional[str]) -> Dict[str, Any]:
    if not entries:
        raise AnalysisError("There is nothing to export yet. Run an analysis first.")
    kind = _infer_format(path, fmt)
    if kind == "txt":
        content = log_to_text(entries)
    elif kind == "html":
        content = log_to_html(entries)
    else:
        content = log_to_csv(entries)
        if not content.strip():
            raise AnalysisError("The selected output contains no tables to write as CSV.")
    try:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
    except OSError as exc:
        raise AnalysisError(f"Could not write '{path}': {exc.strerror or exc}") from exc
    return {"ok": True, "error": None, "path": path, "format": kind}


@_safe
def export_log(entries: Sequence[Dict[str, Any]], path: str, fmt: Optional[str] = None) -> Dict[str, Any]:
    """Export the whole output log to TXT, CSV or HTML (chosen by extension or ``fmt``)."""
    return _write_entries(entries, path, fmt)


def list_exportable_tables(entries: Sequence[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
    """Return ``(entry_index, table_name, display_label)`` for every table in the log."""
    out = []
    for i, e in enumerate(entries):
        for name in e.get("tables", {}):
            out.append((i, name, f"#{i + 1}  {e['title']}  >  {name}"))
    return out


@_safe
def export_tables(
    entries: Sequence[Dict[str, Any]],
    selections: Sequence[Tuple[int, str]],
    path: str,
    fmt: Optional[str] = None,
) -> Dict[str, Any]:
    """Export individual tables, given as ``(entry_index, table_name)`` pairs."""
    if not selections:
        raise AnalysisError("No tables selected.")
    chosen = []
    for idx, name in selections:
        try:
            e = entries[idx]
            tdf = e["tables"][name]
        except (IndexError, KeyError):
            raise AnalysisError(f"Table '{name}' is no longer available.") from None
        dec = e.get("decimals", {}).get(name, 4)
        chosen.append(
            {
                "timestamp": e["timestamp"],
                "title": e["title"],
                "text": f"{name}\n{render_table_text(tdf, dec)}",
                "html": f"<h2>{_html.escape(e['title'])}</h2><h3>{_html.escape(name)}</h3>"
                f'<div class="table-wrap">{render_table_html(tdf, dec)}</div>',
                "tables": {name: tdf},
                "decimals": {name: dec},
            }
        )
    return _write_entries(chosen, path, fmt)
