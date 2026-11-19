# So, this script turns the big free FNSPID news file into a small, clean headline panel
# for the replication window of Lopez-Lira & Tang (2024): October 2021 to December 2023.
#
# let's do now the two steps (inside the same venv):
#   1. Download the raw file once (about 5.7 GB; -C - lets it resume if wifi drops):
#        curl -L -C - -o All_external.csv https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/All_external.csv
#   2. Filter it (reads in chunks, so a laptop never runs out of memory):
#        pip install pandas pandas_market_calendars
#        python fnspid_filter.py --input All_external.csv
#
# Finally, the output lands in fnspid_output/ and is only a few hundred MB at most.

import argparse
from pathlib import Path

import pandas as pd

NEWYORK_TZ = "America/New_York"
WINDOW_FIRST_MONTH = "2021-10"
WINDOW_LAST_MONTH = "2023-12"
WANTED_COLUMNS = {"Date", "Article_title", "Stock_symbol", "Url", "Publisher"}


def nyse_session_days(first_day, last_day):
    # So, we use the real NYSE calendar so holidays are skipped.
    try:
        import pandas_market_calendars as market_cal
        nyse_calendar = market_cal.get_calendar("NYSE")
        session_index = nyse_calendar.schedule(start_date=first_day, end_date=last_day).index
        return pd.DatetimeIndex(session_index).normalize()
    except ImportError:
        print("   pandas_market_calendars not installed -> using weekdays (holidays not removed)")
        return pd.bdate_range(first_day, last_day)


def filter_window(raw_path, rows_per_chunk=200_000):
    kept_pieces = []
    scanned_rows = 0
    year_tally = {}

    # In my opinion, skipping the full article text columns is what makes this fast,
    # because we only need the headline, exactly like the paper.
    chunk_reader = pd.read_csv(raw_path, usecols=lambda column_name: column_name in WANTED_COLUMNS,
                               dtype=str, chunksize=rows_per_chunk, on_bad_lines="skip")
    for chunk_number, news_chunk in enumerate(chunk_reader, start=1):
        scanned_rows += len(news_chunk)
        month_prefix = news_chunk["Date"].fillna("").str.slice(0, 7)
        for year_label, year_count in month_prefix.str.slice(0, 4).value_counts().items():
            year_tally[year_label] = year_tally.get(year_label, 0) + int(year_count)

        in_window = (month_prefix >= WINDOW_FIRST_MONTH) & (month_prefix <= WINDOW_LAST_MONTH)
        if in_window.any():
            kept_pieces.append(news_chunk.loc[in_window])
        if chunk_number % 10 == 0:
            kept_so_far = sum(len(piece) for piece in kept_pieces)
            print(f"   scanned {scanned_rows:,} rows, kept {kept_so_far:,} so far ...")

    print(f"   scanned {scanned_rows:,} rows in total")
    return (pd.concat(kept_pieces, ignore_index=True) if kept_pieces
            else pd.DataFrame(columns=sorted(WANTED_COLUMNS))), year_tally


def build_ticker_panel(window_frame, trading_days):
    # let's do now the same timing rules as our Alpaca panel:
    #   before 09:00 ET on a trading day          -> overnight, trade that same day
    #   after 16:00 ET, weekend or holiday        -> overnight, trade the next trading day
    #   09:00-16:00 ET on a trading day           -> intraday, trade that same day
    # In my opinion, a timestamp of exactly 00:00:00 UTC usually means "date only", so we
    # treat those conservatively as after-close news; that can only delay, never leak.
    panel_frame = window_frame.rename(columns={"Article_title": "headline", "Stock_symbol": "ticker",
                                               "Publisher": "publisher", "Url": "url"}).copy()
    panel_frame["headline"] = panel_frame["headline"].fillna("").str.strip()
    panel_frame["ticker"] = panel_frame["ticker"].fillna("").str.strip().str.upper()
    panel_frame = panel_frame[(panel_frame["headline"] != "") & (panel_frame["ticker"] != "")]

    parsed_utc = pd.to_datetime(panel_frame["Date"], utc=True, errors="coerce", format="mixed")
    panel_frame = panel_frame.loc[parsed_utc.notna()].copy()
    parsed_utc = parsed_utc[parsed_utc.notna()]

    date_only_stamp = (parsed_utc.dt.hour == 0) & (parsed_utc.dt.minute == 0) & (parsed_utc.dt.second == 0)
    panel_frame["time_precision"] = "minute"
    panel_frame.loc[date_only_stamp, "time_precision"] = "day"

    panel_frame["created_at_ny"] = parsed_utc.dt.tz_convert(NEWYORK_TZ)
    panel_frame.loc[date_only_stamp, "created_at_ny"] = (
        parsed_utc[date_only_stamp].dt.tz_localize(None).dt.tz_localize(NEWYORK_TZ)
        + pd.Timedelta(hours=23, minutes=59))

    panel_frame["calendar_date"] = panel_frame["created_at_ny"].dt.tz_localize(None).dt.normalize()
    clock_minutes = panel_frame["created_at_ny"].dt.hour * 60 + panel_frame["created_at_ny"].dt.minute
    is_session_day = panel_frame["calendar_date"].isin(trading_days)
    before_nine = clock_minutes < 9 * 60
    after_four = clock_minutes >= 16 * 60

    panel_frame["news_timing"] = "intraday"
    panel_frame.loc[~is_session_day | before_nine | after_four, "news_timing"] = "overnight"

    # So, first_trade_date is the first day an investor could actually act on the news.
    sorted_days = pd.DatetimeIndex(sorted(trading_days))
    same_day_ok = is_session_day & ~after_four
    day_position = sorted_days.searchsorted(panel_frame["calendar_date"], side="left")
    next_position = sorted_days.searchsorted(panel_frame["calendar_date"], side="right")
    chosen_position = pd.Series(next_position, index=panel_frame.index)
    chosen_position[same_day_ok] = pd.Series(day_position, index=panel_frame.index)[same_day_ok]
    in_range = chosen_position < len(sorted_days)
    panel_frame["first_trade_date"] = pd.NaT
    panel_frame.loc[in_range, "first_trade_date"] = sorted_days[chosen_position[in_range]]

    # So, repeated headlines for the same ticker and trade date are dropped, like in the paper.
    panel_frame = panel_frame.drop_duplicates(subset=["ticker", "first_trade_date", "headline"])
    keep_columns = ["ticker", "created_at_ny", "time_precision", "news_timing", "first_trade_date",
                    "headline", "publisher", "url"]
    return panel_frame[keep_columns].sort_values(["created_at_ny", "ticker"])


def main():
    cli = argparse.ArgumentParser(description="Filter FNSPID news to the Oct 2021 - Dec 2023 window.")
    cli.add_argument("--input", required=True, help="Path to All_external.csv (or nasdaq_exteral_data.csv)")
    cli.add_argument("--outdir", default="fnspid_output")
    user_choice = cli.parse_args()

    output_folder = Path(user_choice.outdir)
    output_folder.mkdir(exist_ok=True)
    source_label = Path(user_choice.input).stem

    print(f"Reading {user_choice.input} ...")
    window_frame, year_tally = filter_window(user_choice.input)
    window_frame.to_csv(output_folder / f"{source_label}_2021_2023_raw.csv", index=False)

    print("\nRows per year in the whole file:")
    for year_label in sorted(label for label in year_tally if label.isdigit()):
        print(f"   {year_label}: {year_tally[year_label]:,}")

    if window_frame.empty:
        print("\nNo rows fell inside Oct 2021 - Dec 2023 in this file.")
        return

    trading_days = nyse_session_days("2021-09-01", "2024-01-31")
    research_panel = build_ticker_panel(window_frame, trading_days)
    research_panel.to_csv(output_folder / f"{source_label}_panel_2021_2023.csv", index=False)

    # Finally, a quick summary to quote on the data slide.
    print("\nDone.")
    print(f"  headline-ticker rows:  {len(research_panel):,}")
    print(f"  unique tickers:        {research_panel['ticker'].nunique():,}")
    print(f"  minute-level stamps:   {(research_panel['time_precision'] == 'minute').mean():.1%}")
    print(f"  overnight share:       {(research_panel['news_timing'] == 'overnight').mean():.1%}")
    print(f"  files in:              {output_folder.resolve()}")


if __name__ == "__main__":
    main()
