# So, this script downloads free daily stock prices from Alpaca for every ticker that
# appears in our news panels, and builds the returns the Lopez-Lira & Tang strategy trades:
#   ret_oc         open -> close of the same day   (overnight news, entered at the open)
#   ret_cc         close -> close                  (holding-period and decay analysis)
#   ret_overnight  previous close -> open          (the market's first reaction to news)
# It also saves Alpaca's asset list, which tells us if a stock is shortable and easy to borrow.
#
# let's do now the runs (inside the same venv, with the same APCA keys set):
#   pip install requests pandas
#   python alpaca_price_pull.py --panels alpaca_news_output/alpaca_news_panel.csv --start 2026-03-15 --end 2026-11-18 --label 2026
#   python alpaca_price_pull.py --panels fnspid_output/All_external_panel_2021_2023.csv --start 2021-09-15 --end 2024-01-31 --label 2021_2023
#
# Finally, files land in price_data_output/

import argparse
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ALPACA_BARS_ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_ASSETS_ENDPOINT = "https://paper-api.alpaca.markets/v2/assets"
NEWYORK_TZ = "America/New_York"
US_TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}([.][A-Z]{1,2})?$")


def build_auth_headers():
    # So, the keys come from the environment, so they never sit inside the code.
    alpaca_key_id = os.environ.get("APCA_API_KEY_ID")
    alpaca_secret = os.environ.get("APCA_API_SECRET_KEY")
    if not alpaca_key_id or not alpaca_secret:
        sys.exit("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY environment variables.")
    return {"APCA-API-KEY-ID": alpaca_key_id, "APCA-API-SECRET-KEY": alpaca_secret}


def polite_get(target_url, auth_headers, query_params, max_retries=8):
    # In my opinion, one helper for rate limits and network drops keeps the rest clean.
    retry_count = 0
    while True:
        try:
            api_reply = requests.get(target_url, headers=auth_headers, params=query_params, timeout=60)
        except requests.exceptions.RequestException as network_problem:
            retry_count += 1
            if retry_count > max_retries:
                raise
            print(f"   network problem ({network_problem.__class__.__name__}), retrying in 10s ...")
            time.sleep(10)
            continue
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
        return api_reply


def collect_tickers(panel_paths):
    gathered_symbols = set()
    for panel_path in panel_paths:
        panel_tickers = pd.read_csv(panel_path, usecols=["ticker"], dtype=str)["ticker"]
        gathered_symbols.update(panel_tickers.dropna().str.strip().str.upper())
    # So, Alpaca writes class shares with a dot (BRK.B), so we convert dashes and slashes.
    cleaned_symbols = {symbol_text.replace("-", ".").replace("/", ".") for symbol_text in gathered_symbols}
    us_style = sorted(symbol_text for symbol_text in cleaned_symbols if US_TICKER_PATTERN.match(symbol_text))
    print(f"tickers in panels: {len(cleaned_symbols):,}  ->  US-style symbols kept: {len(us_style):,}")
    return us_style


def fetch_asset_list(auth_headers):
    api_reply = polite_get(ALPACA_ASSETS_ENDPOINT, auth_headers, {"asset_class": "us_equity"})
    if api_reply.status_code == 401:
        sys.exit("401: Alpaca rejected the keys. Check APCA_API_KEY_ID and APCA_API_SECRET_KEY.")
    api_reply.raise_for_status()
    asset_frame = pd.DataFrame(api_reply.json())
    keep_fields = [field_name for field_name in
                   ["symbol", "name", "exchange", "status", "tradable", "shortable",
                    "easy_to_borrow", "borrow_status", "marginable", "fractionable", "attributes"]
                   if field_name in asset_frame.columns]
    return asset_frame[keep_fields]


def fetch_daily_bars(auth_headers, symbol_list, range_start, range_end, price_adjustment,
                     data_feed="sip", batch_size=100, pause_seconds=0.35):
    harvested_bars = []
    batch_starts = range(0, len(symbol_list), batch_size)
    for batch_number, batch_begin in enumerate(batch_starts, start=1):
        symbol_batch = symbol_list[batch_begin:batch_begin + batch_size]
        continuation_token = None
        while True:
            # So, asof = start date means each ticker is read as it was named back then
            # (for example FB in 2021 instead of META), which matches our news files.
            query_params = {
                "symbols": ",".join(symbol_batch),
                "timeframe": "1Day",
                "start": range_start,
                "end": range_end,
                "limit": 10000,
                "adjustment": price_adjustment,
                "feed": data_feed,
                "asof": range_start,
                "sort": "asc",
            }
            if continuation_token:
                query_params["page_token"] = continuation_token
            api_reply = polite_get(ALPACA_BARS_ENDPOINT, auth_headers, query_params)

            if api_reply.status_code == 403 and data_feed == "sip":
                print("   403 on the SIP feed -> switching to the free IEX feed")
                data_feed = "iex"
                continue
            if api_reply.status_code == 401:
                sys.exit("401: Alpaca rejected the keys. Check APCA_API_KEY_ID and APCA_API_SECRET_KEY.")
            api_reply.raise_for_status()

            reply_payload = api_reply.json()
            for bar_symbol, symbol_bars in (reply_payload.get("bars") or {}).items():
                for single_bar in symbol_bars:
                    single_bar["ticker"] = bar_symbol
                    harvested_bars.append(single_bar)
            continuation_token = reply_payload.get("next_page_token")
            time.sleep(pause_seconds)
            if not continuation_token:
                break
        print(f"   {price_adjustment:>4s} bars: batch {batch_number}/{len(batch_starts)} done "
              f"({len(harvested_bars):,} bars so far)")

    bar_frame = pd.DataFrame(harvested_bars)
    if bar_frame.empty:
        return bar_frame, data_feed
    bar_frame = bar_frame.rename(columns={"t": "bar_time", "o": "open", "h": "high", "l": "low", "c": "close",
                                          "v": "volume", "n": "trade_count", "vw": "vwap"})
    # In my opinion, daily bars are stamped at midnight New York time, so converting to
    # New York before taking the date is the safe way to get the right trading day.
    bar_frame["date"] = (pd.to_datetime(bar_frame["bar_time"], utc=True)
                         .dt.tz_convert(NEWYORK_TZ).dt.tz_localize(None).dt.normalize())
    return bar_frame.drop(columns=["bar_time"]), data_feed


def add_strategy_returns(adjusted_bars, raw_bars):
    price_table = adjusted_bars.sort_values(["ticker", "date"]).copy()
    previous_close = price_table.groupby("ticker")["close"].shift(1)
    price_table["ret_oc"] = price_table["close"] / price_table["open"] - 1
    price_table["ret_cc"] = price_table["close"] / previous_close - 1
    price_table["ret_overnight"] = price_table["open"] / previous_close - 1

    # So, the raw (unadjusted) close is what the paper's "price above $5" filter needs.
    if raw_bars is not None and not raw_bars.empty:
        raw_slice = raw_bars[["ticker", "date", "close"]].rename(columns={"close": "raw_close"})
        price_table = price_table.merge(raw_slice, on=["ticker", "date"], how="left")
        price_table["dollar_volume"] = price_table["raw_close"] * price_table["volume"]
    return price_table


def main():
    cli = argparse.ArgumentParser(description="Download Alpaca daily prices for tickers in our news panels.")
    cli.add_argument("--panels", nargs="+", required=True, help="One or more panel CSVs with a 'ticker' column")
    cli.add_argument("--start", required=True, help="YYYY-MM-DD (start a few weeks before your news)")
    cli.add_argument("--end", required=True, help="YYYY-MM-DD (end a few weeks after your news)")
    cli.add_argument("--label", required=True, help="Short name for the output files, e.g. 2026")
    cli.add_argument("--outdir", default="price_data_output")
    user_choice = cli.parse_args()

    output_folder = Path(user_choice.outdir)
    output_folder.mkdir(exist_ok=True)
    auth_headers = build_auth_headers()

    # let's do now the ticker universe and the asset list.
    symbol_list = collect_tickers(user_choice.panels)
    asset_table = fetch_asset_list(auth_headers)
    asset_table.to_csv(output_folder / "alpaca_assets.csv", index=False)
    known_symbols = set(asset_table["symbol"])
    print(f"Alpaca knows {sum(symbol_text in known_symbols for symbol_text in symbol_list):,} "
          f"of our {len(symbol_list):,} symbols (delisted names may still have bars)")

    # So, adjusted bars give correct returns, raw bars give the real traded price.
    adjusted_bars, used_feed = fetch_daily_bars(auth_headers, symbol_list, user_choice.start,
                                                user_choice.end, "all")
    if adjusted_bars.empty:
        sys.exit("No bars came back. Check the dates and that the market was open in that range.")
    raw_bars, _ = fetch_daily_bars(auth_headers, symbol_list, user_choice.start,
                                   user_choice.end, "raw", data_feed=used_feed)

    # Finally, returns plus the asset flags, saved as one tidy daily file.
    price_table = add_strategy_returns(adjusted_bars, raw_bars)
    flag_columns = [column_name for column_name in ["symbol", "exchange", "shortable", "easy_to_borrow",
                                                    "borrow_status"] if column_name in asset_table.columns]
    price_table = price_table.merge(asset_table[flag_columns].rename(columns={"symbol": "ticker"}),
                                    on="ticker", how="left")
    leading_columns = ["ticker", "date"]
    price_table = price_table[leading_columns + [column_name for column_name in price_table.columns
                                                 if column_name not in leading_columns]]
    output_path = output_folder / f"daily_prices_{user_choice.label}.csv"
    price_table.to_csv(output_path, index=False)

    print("\nDone.")
    print(f"  feed used:        {used_feed}")
    print(f"  tickers with data:{price_table['ticker'].nunique():>8,}")
    print(f"  ticker-days:      {len(price_table):>8,}")
    print(f"  date range:       {price_table['date'].min().date()} -> {price_table['date'].max().date()}")
    print(f"  file:             {output_path.resolve()}")


if __name__ == "__main__":
    main()
