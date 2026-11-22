# A.L.M.O.N.D.S
**A Lot of Math On Neat Data Sheets** - a simple desktop statistics workbench in Python, inspired by Excel and SPSS workflows.

Almond-themed Tkinter GUI (cream background, espresso text, warm brown accents, light-brown window border, 96% window opacity) on top of a GUI-free statistics engine built with pandas, NumPy, SciPy, statsmodels and openpyxl.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python almonds/almonds_app.py      # or: python -m almonds.almonds_app
```

Then choose **Open Data** (Ctrl+O) and load `sample_data/sample_survey.csv`.
Linux users may need `sudo apt install python3-tk` for Tkinter.

## Project layout

```
A.L.M.O.N.D.S/
├── almonds/
│   ├── almonds_app.py      # Tkinter GUI, event handling, output rendering
│   └── stats_engine.py     # Pure statistics + file I/O (zero GUI imports)
├── sample_data/
│   └── sample_survey.csv   # 200-row synthetic survey with realistic missing values
├── requirements.txt
└── README.md
```

## Features

| Module | What you get |
|---|---|
| **Data import & inspection** | `.csv`, `.tsv`, `.xlsx` (worksheet picker for multi-sheet books). Column names, inferred types, row/column counts, per-column missing counts and percentages, scrollable data sheet preview and a metadata side panel. |
| **Descriptive statistics** | Univariate table (n, missing, mean, SD, variance, min, max); quartiles, median, IQR, custom percentiles, skewness, excess kurtosis; frequency tables (count, %, valid %, cumulative %); 2-way cross-tabulations with optional row/column/total percentages. |
| **Hypothesis testing** | Chi-square test of independence (observed, expected, standardized residuals, chi-square, likelihood ratio, df, p-value, Yates correction for 2x2, Cramer's V) and chi-square goodness-of-fit (equal or custom expected proportions). |
| **Correlation & regression** | Pearson r and Spearman rho matrices with pairwise N and two-tailed p-values; simple and multiple OLS regression with model summary (R, R², adjusted R², F, p), ANOVA table, and coefficients (estimate, SE, standardized beta, t, p, 95% CI). |
| **Output & export** | Every analysis is appended to a timestamped, scrollable Output Log. Export the whole log or selected result tables to **TXT**, **CSV** or **HTML** (Almond-themed). |

## Using the engine without the GUI

```python
from almonds import stats_engine as se

data = se.load_file("sample_data/sample_survey.csv")["data"]
res = se.linear_regression(data, "job_satisfaction", ["annual_income_k", "stress_level"])
if res["ok"]:
    print(res["text"])                 # monospace tables
    coef = res["tables"]["Coefficients"]   # pandas DataFrame
    r2 = res["stats"]["r_squared"]
else:
    print(res["error"])                # clear, user-facing message
```

Every analysis function takes a `DataFrame` plus column names and returns a dictionary with `ok`, `error`, `title`, `text`, `html`, `tables` (DataFrames) and `stats`. Functions never raise; non-numeric columns, empty selections, constant variables, singular (perfectly collinear) design matrices and unreadable files all come back as `ok=False` with an explanatory message.

## Statistical notes

- SD and variance use the sample (n - 1) denominator; percentiles use linear interpolation.
- Skewness is the adjusted Fisher-Pearson coefficient; kurtosis is *excess* kurtosis (normal = 0).
- Correlations use pairwise deletion; regression and chi-square use listwise deletion of rows with missing values in the chosen variables.
- Chi-square warns when expected counts fall below 5.
- Regression predictors must be numeric (dummy-code categorical predictors first).
- Limits: frequency tables up to 200 distinct values, cross-tabs/chi-square up to 50 categories per variable; the data sheet preview shows the first 1,000 rows (analyses always use all rows).

## Sample data

`sample_data/sample_survey.csv` is synthetic (200 respondents; age, gender, region, education, employment, income, hours, remote work, exercise, sleep, stress, job and life satisfaction) with ~1-6% missing values in several columns. Handy tests: chi-square of `education` x `remote_work`; regression of `job_satisfaction` on `annual_income_k` and `stress_level`.
