# So, this script downloads every benchmark series we need for the risk-adjustment
# and regime parts of our MGT 6078 project, all from free public sources:
#   - Ken French Data Library (daily): FF3, FF5, Momentum, Short-Term Reversal
#   - global-q.org (daily): q-factor / q5 model
#   - FRED (daily): VIX, for the high vs low volatility regime split
#
# let's do now the run (inside the same venv):
#   pip install requests pandas
#   python factor_data_pull.py
#
# Finally, everything lands in the folder factor_data_output/

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FRENCH_DAILY_FILES = {
    "ff3": "F-F_Research_Data_Factors_daily_CSV.zip",
    "ff5": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "mom": "F-F_Momentum_Factor_daily_CSV.zip",
    "strev": "F-F_ST_Reversal_Factor_daily_CSV.zip",
}
QFACTOR_DAILY_URL = "https://global-q.org/uploads/1/2/2/6/122679606/q5_factors_daily_2025.csv"
FRED_VIX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (MGT6078 student project)"}


def download_bytes(source_url):
    server_reply = requests.get(source_url, headers=BROWSER_HEADERS, timeout=60)
    server_reply.raise_for_status()
    return server_reply.content


def parse_french_daily(zip_payload):
    # So, French's CSVs have text above and below the table, so we keep only the block
    # that starts at the header row and continues while the first field is an 8-digit date.
    with zipfile.ZipFile(io.BytesIO(zip_payload)) as french_zip:
        inner_name = french_zip.namelist()[0]
        raw_text = french_zip.read(inner_name).decode("latin-1")

    text_lines = raw_text.splitlines()
    header_fields, data_rows = None, []
    for line_index, current_line in enumerate(text_lines):
        leading_field = current_line.split(",")[0].strip()
        if header_fields is None:
            upcoming_line = text_lines[line_index + 1] if line_index + 1 < len(text_lines) else ""
            upcoming_field = upcoming_line.split(",")[0].strip()
            if current_line.strip().startswith(",") and upcoming_field.isdigit() and len(upcoming_field) == 8:
                header_fields = [piece.strip() for piece in current_line.split(",")[1:]]
            continue
        if leading_field.isdigit() and len(leading_field) == 8:
            data_rows.append([piece.strip() for piece in current_line.split(",")])
        else:
            break

    if header_fields is None:
        raise ValueError("Could not find the daily table inside the French file.")

    french_frame = pd.DataFrame(data_rows, columns=["date"] + header_fields)
    french_frame["date"] = pd.to_datetime(french_frame["date"], format="%Y%m%d")
    for factor_column in header_fields:
        french_frame[factor_column] = pd.to_numeric(french_frame[factor_column], errors="coerce")
        # In my opinion, -99.99 is French's missing-value code, so it must become NaN.
        french_frame.loc[french_frame[factor_column] <= -99.99, factor_column] = pd.NA
    return french_frame


def parse_qfactor_daily(csv_payload):
    # So, q5 values are in percent like French's. In my opinion, the date column has
    # changed format across releases (19670103 vs 1967-01-03), so let's accept both.
    q_frame = pd.read_csv(io.BytesIO(csv_payload))
    q_frame.columns = [column_name.strip().upper() for column_name in q_frame.columns]
    date_column = "DATE" if "DATE" in q_frame.columns else q_frame.columns[0]
    date_strings = q_frame[date_column].astype(str).str.strip()
    if date_strings.str.fullmatch(r"\d{8}").all():
        q_frame["date"] = pd.to_datetime(date_strings, format="%Y%m%d")
    else:
        q_frame["date"] = pd.to_datetime(date_strings, format="ISO8601")
    q_frame = q_frame.drop(columns=[date_column])
    return q_frame.rename(columns={column_name: f"q_{column_name}" for column_name in q_frame.columns
                                   if column_name != "date"})


def parse_fred_vix(csv_payload):
    # In my opinion, FRED renamed its date column before, so let's accept either name.
    vix_frame = pd.read_csv(io.BytesIO(csv_payload), na_values=["."])
    date_column = "observation_date" if "observation_date" in vix_frame.columns else vix_frame.columns[0]
    vix_frame = vix_frame.rename(columns={date_column: "date", "VIXCLS": "vix"})
    vix_frame["date"] = pd.to_datetime(vix_frame["date"])
    vix_frame["vix"] = pd.to_numeric(vix_frame["vix"], errors="coerce")
    return vix_frame[["date", "vix"]]


def main():
    output_folder = Path("factor_data_output")
    output_folder.mkdir(exist_ok=True)
    collected_tables = {}

    # let's do now the four French daily files.
    for short_label, zip_name in FRENCH_DAILY_FILES.items():
        try:
            french_table = parse_french_daily(download_bytes(FRENCH_BASE + zip_name))
            french_table.to_csv(output_folder / f"french_{short_label}_daily.csv", index=False)
            collected_tables[short_label] = french_table
            print(f"french {short_label:6s}: {len(french_table):,} days, "
                  f"{french_table['date'].min().date()} -> {french_table['date'].max().date()}")
        except Exception as french_problem:
            print(f"french {short_label:6s}: FAILED ({french_problem})")

    # So, next the q-factor model.
    try:
        q_table = parse_qfactor_daily(download_bytes(QFACTOR_DAILY_URL))
        q_table.to_csv(output_folder / "qfactor_q5_daily.csv", index=False)
        collected_tables["q5"] = q_table
        print(f"q5 factors  : {len(q_table):,} days, "
              f"{q_table['date'].min().date()} -> {q_table['date'].max().date()}")
    except Exception as q_problem:
        print(f"q5 factors  : FAILED ({q_problem}) -> check the newest file name on global-q.org")

    # So, and the VIX for the regime analysis.
    try:
        vix_table = parse_fred_vix(download_bytes(FRED_VIX_URL))
        vix_table.to_csv(output_folder / "fred_vix_daily.csv", index=False)
        collected_tables["vix"] = vix_table
        print(f"VIX         : {vix_table['vix'].notna().sum():,} days, "
              f"{vix_table['date'].min().date()} -> {vix_table['date'].max().date()}")
    except Exception as vix_problem:
        print(f"VIX         : FAILED ({vix_problem})")

    if "ff5" not in collected_tables:
        sys.exit("FF5 is required for the merged file; fix the download and re-run.")

    # Finally, one merged daily file from 2021 onward, all in percent (VIX in index points).
    merged_factors = collected_tables["ff5"].copy()
    if "mom" in collected_tables:
        merged_factors = merged_factors.merge(collected_tables["mom"], on="date", how="left")
    if "strev" in collected_tables:
        merged_factors = merged_factors.merge(collected_tables["strev"], on="date", how="left")
    if "q5" in collected_tables:
        merged_factors = merged_factors.merge(collected_tables["q5"], on="date", how="left")
    if "vix" in collected_tables:
        merged_factors = merged_factors.merge(collected_tables["vix"], on="date", how="left")
    merged_factors.columns = [column_name.strip().replace(" ", "") for column_name in merged_factors.columns]
    merged_factors = merged_factors[merged_factors["date"] >= "2021-01-01"]
    merged_factors.to_csv(output_folder / "factors_daily_merged_2021on.csv", index=False)

    print(f"\nmerged file : {len(merged_factors):,} days, columns = {list(merged_factors.columns)}")
    print(f"files in    : {output_folder.resolve()}")


if __name__ == "__main__":
    main()
