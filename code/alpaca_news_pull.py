# So, this script pulls historical Benzinga news headlines from the Alpaca News API
# and saves them as CSV files for our MGT 6078 project on Lopez-Lira & Tang (2024).
#
# let's do now the setup before running:
#   pip install requests pandas pandas_market_calendars
#   Mac:      export APCA_API_KEY_ID="..."   and   export APCA_API_SECRET_KEY="..."
#   Windows:  set APCA_API_KEY_ID=...        and   set APCA_API_SECRET_KEY=...
#
# Finally, run it like this:
#   python alpaca_news_pull.py --start 2024-01-01 --end 2026-10-31
#   python alpaca_news_pull.py --start 2024-01-01 --end 2024-01-31 --tickers AAPL,MSFT

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ALPACA_NEWS_ENDPOINT = "https://data.alpaca.markets/v1beta1/news"
NEWYORK_TZ = "America/New_York"
ARTICLE_COLUMNS = ["article_id", "created_at_utc", "updated_at_utc", "headline", "summary",
                   "symbols", "num_symbols", "source", "author", "url"]


def build_auth_headers():
    # So, the keys come from the environment, so they never sit inside the code.
    alpaca_key_id = os.environ.get("APCA_API_KEY_ID")
    alpaca_secret = os.environ.get("APCA_API_SECRET_KEY")
    if not alpaca_key_id or not alpaca_secret:
        sys.exit("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY environment variables.")
    return {"APCA-API-KEY-ID": alpaca_key_id, "APCA-API-SECRET-KEY": alpaca_secret}


def fetch_one_window(auth_headers, window_start, window_end, ticker_filter=None,
                     pause_seconds=0.35, max_retries=8):
    harvested_articles = []
    continuation_token = None
    retry_count = 0

    while True:
        # So, 50 articles per page is the maximum the API allows.
        query_params = {
            "start": window_start,
            "end": window_end,
            "limit": 50,
            "sort": "asc",
            "include_content": "false",
        }
        if ticker_filter:
            query_params["symbols"] = ticker_filter
        if continuation_token:
            query_params["page_token"] = continuation_token

        # In my opinion, network drops happen on long pulls, so let's retry instead of crashing.
        try:
            api_reply = requests.get(ALPACA_NEWS_ENDPOINT, headers=auth_headers,
                                     params=query_params, timeout=30)
        except requests.exceptions.RequestException as network_problem:
            retry_count += 1
            if retry_count > max_retries:
                raise
            print(f"   network problem ({network_problem.__class__.__name__}), retrying in 10s ...")
            time.sleep(10)
            continue

        if api_reply.status_code == 401:
            sys.exit("401: Alpaca rejected the keys. Check APCA_API_KEY_ID and APCA_API_SECRET_KEY.")
        if api_reply.status_code == 403:
            sys.exit("403: your Alpaca plan does not cover this news data. Check your subscription.")
        if api_reply.status_code == 429:
            reset_epoch = api_reply.headers.get("X-RateLimit-Reset")
            wait_for = max(int(reset_epoch) - time.time(), 1) if reset_epoch else 30
            print(f"   rate-limited, sleeping {wait_for:.0f}s ...")
            time.sleep(wait_for)
            continue
        if api_reply.status_code >= 500:
            retry_count += 1
            if retry_count > max_retries:
                api_reply.raise_for_status()
            print("   server hiccup, retrying in 10s ...")
            time.sleep(10)
            continue
        api_reply.raise_for_status()

        retry_count = 0
        reply_payload = api_reply.json()
        harvested_articles.extend(reply_payload.get("news") or [])
        continuation_token = reply_payload.get("next_page_token")

        # So, sleeping ~0.35s keeps us near 170 calls per minute, under the free 200 cap.
        time.sleep(pause_seconds)
        if not continuation_token:
            break

    return harvested_articles


def month_windows(first_day, last_day):
    # So, we split the range into months so a crash never loses the whole download.
    # In my opinion, the end must be 23:59:59, because a bare date means midnight
    # and would silently drop the last day of every month.
    range_begin = pd.Timestamp(first_day)
    range_finish = pd.Timestamp(last_day)
    month_starts = pd.date_range(range_begin.replace(day=1), range_finish, freq="MS")
    window_pairs = []
    for month_begin in month_starts:
        month_close = month_begin + pd.offsets.MonthEnd(0)
        begin_clip = max(month_begin, range_begin)
        close_clip = min(month_close, range_finish)
        window_pairs.append((begin_clip.strftime("%Y-%m-%dT00:00:00Z"),
                             close_clip.strftime("%Y-%m-%dT23:59:59Z")))
    return window_pairs


def flatten_articles(article_list):
    flat_rows = []
    for single_article in article_list:
        tagged_symbols = single_article.get("symbols") or []
        flat_rows.append({
            "article_id": single_article.get("id"),
            # In my opinion, created_at is the only safe timestamp; updated_at can come
            # hours later and would leak future information into our signal.
            "created_at_utc": single_article.get("created_at"),
            "updated_at_utc": single_article.get("updated_at"),
            "headline": (single_article.get("headline") or "").strip(),
            "summary": (single_article.get("summary") or "").strip(),
            "symbols": ",".join(tagged_symbols),
            "num_symbols": len(tagged_symbols),
            "source": single_article.get("source"),
            "author": single_article.get("author"),
            "url": single_article.get("url"),
        })
    # So, an empty month still gets proper column headers.
    return pd.DataFrame(flat_rows, columns=ARTICLE_COLUMNS)


def nyse_session_days(first_day, last_day):
    # So, we use the real NYSE calendar so holidays like Good Friday are skipped.
    try:
        import pandas_market_calendars as market_cal
        nyse_calendar = market_cal.get_calendar("NYSE")
        session_index = nyse_calendar.schedule(start_date=first_day, end_date=last_day).index
        return pd.DatetimeIndex(session_index).normalize()
    except ImportError:
        print("   pandas_market_calendars not installed -> using weekdays (holidays not removed)")
        return pd.bdate_range(first_day, last_day)


def build_ticker_panel(raw_frame, trading_days):
    # let's do now the paper's timing rules, one row per (article, ticker):
    #   before 09:00 ET on a trading day          -> overnight, trade that same day
    #   after 16:00 ET, weekend or holiday        -> overnight, trade the next trading day
    #   09:00-16:00 ET on a trading day           -> intraday, trade that same day
    panel_frame = raw_frame.dropna(subset=["created_at_utc"]).copy()
    panel_frame["created_at_ny"] = (pd.to_datetime(panel_frame["created_at_utc"], utc=True)
                                    .dt.tz_convert(NEWYORK_TZ))
    panel_frame["calendar_date"] = panel_frame["created_at_ny"].dt.tz_localize(None).dt.normalize()
    clock_minutes = (panel_frame["created_at_ny"].dt.hour * 60
                     + panel_frame["created_at_ny"].dt.minute)

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

    # So, an article tagged with three tickers becomes three rows.
    panel_frame["ticker"] = panel_frame["symbols"].fillna("").str.split(",")
    panel_frame = panel_frame.explode("ticker")
    panel_frame = panel_frame[panel_frame["ticker"].notna() & (panel_frame["ticker"] != "")]

    # In my opinion, a single-ticker article is our closest free match to RavenPack
    # relevance = 100, because it is almost surely about that one firm.
    panel_frame["single_firm_article"] = panel_frame["num_symbols"] == 1

    # So, repeated headlines for the same ticker and trade date are dropped, like in the paper.
    panel_frame = panel_frame.drop_duplicates(subset=["ticker", "first_trade_date", "headline"])

    keep_columns = ["article_id", "ticker", "created_at_ny", "news_timing", "first_trade_date",
                    "headline", "summary", "num_symbols", "single_firm_article", "source", "url"]
    return panel_frame[keep_columns].sort_values(["created_at_ny", "ticker"])


def main():
    cli = argparse.ArgumentParser(description="Download Alpaca/Benzinga news to CSV.")
    cli.add_argument("--start", required=True, help="YYYY-MM-DD")
    cli.add_argument("--end", required=True, help="YYYY-MM-DD")
    cli.add_argument("--tickers", default=None,
                     help="Optional comma list, e.g. AAPL,MSFT. Leave empty for ALL news.")
    cli.add_argument("--outdir", default="alpaca_news_output")
    user_choice = cli.parse_args()

    output_folder = Path(user_choice.outdir)
    monthly_folder = output_folder / "monthly_chunks"
    monthly_folder.mkdir(parents=True, exist_ok=True)
    auth_headers = build_auth_headers()

    # let's do now the download month by month; months already saved are skipped on re-runs.
    for window_start, window_end in month_windows(user_choice.start, user_choice.end):
        month_label = window_start[:7]
        chunk_path = monthly_folder / f"news_{month_label}.csv"
        if chunk_path.exists():
            print(f"{month_label}: already saved, skipping")
            continue
        print(f"{month_label}: downloading ...")
        month_articles = fetch_one_window(auth_headers, window_start, window_end,
                                          ticker_filter=user_choice.tickers)
        flatten_articles(month_articles).to_csv(chunk_path, index=False)
        print(f"   saved {len(month_articles):,} articles")

    # Finally, stitch the months together and build the research panel.
    combined_raw = pd.concat(
        [pd.read_csv(chunk_file) for chunk_file in sorted(monthly_folder.glob("news_*.csv"))],
        ignore_index=True,
    ).drop_duplicates(subset="article_id")
    combined_raw.to_csv(output_folder / "alpaca_news_raw.csv", index=False)

    if combined_raw.empty:
        print("\nNo articles came back for this range, so there is no panel to build.")
        return

    trading_days = nyse_session_days(pd.Timestamp(user_choice.start) - pd.Timedelta(days=10),
                                     pd.Timestamp(user_choice.end) + pd.Timedelta(days=10))
    research_panel = build_ticker_panel(combined_raw, trading_days)
    research_panel.to_csv(output_folder / "alpaca_news_panel.csv", index=False)

    print("\nDone.")
    print(f"  articles:              {len(combined_raw):,}")
    print(f"  article-ticker rows:   {len(research_panel):,}")
    print(f"  single-firm rows:      {int(research_panel['single_firm_article'].sum()):,}")
    print(f"  overnight share:       {(research_panel['news_timing'] == 'overnight').mean():.1%}")
    print(f"  files in:              {output_folder.resolve()}")


if __name__ == "__main__":
    main()
