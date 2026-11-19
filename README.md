# LLM News Alpha

**So, can ChatGPT still beat the market after everyone read the paper that said it could?**

This is Group 5's final project for MGT 6078 Finance and Investments at Georgia Tech (Fall 2026).
We extend Lopez-Lira & Tang (2024), [*Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models*](https://arxiv.org/abs/2304.07619).

🌐 **Project website:** https://anay-a-joshi.github.io/llm-news-alpha/

## The idea

In 2023, Lopez-Lira and Tang showed that just asking GPT-4 "is this headline good or bad for the stock?" predicted next-day returns, with a long-short Sharpe ratio of 3.28. But their own results show the edge shrinking every year as LLMs went mainstream (6.54 → 3.68 → 2.33).

In my opinion, that decline is the most interesting part of the paper. So, instead of just re-running it, we're testing whether the alpha survived, where it survives, and whether it actually pays after trading costs.

## What we're adding

| Extension | The question it answers |
|---|---|
| Fresh 2026 test | Did the alpha shrink after the paper was published and LLMs went mainstream? |
| Gemma 3 model-size ladder (1B, 4B, 12B) | Is there a profitability threshold in model size when the training data stays the same? |
| Signal decay and trading costs | How fast does the signal fade, and what's the break-even trading cost? |
| Risk and cash-flow tests | Does the alpha survive FF3, FF5 and q-factors, and does the score predict earnings surprises? |

## Where we are

- ✅ **2026 news:** 289,217 headlines (April to November 2026), more than twice the paper's 134,129
- ✅ **2026 prices:** 6,030 stocks, 1,014,623 stock-days, from the consolidated SIP feed
- ✅ **Factors:** FF3, FF5, momentum, short-term reversal, q5 factors and VIX
- ⏳ **2021–23 replication data:** FNSPID Nasdaq file, coverage verified
- ⏳ **LLM scoring:** Gemma 3 on Google Colab, using the paper's exact prompt at temperature 0
- 📄 **Final report:** December 15, 2026

## Repository

| Path | What's inside |
|---|---|
| `index.html` | The project website: Overview, Slides, Report (PDF) |
| `assets/img/` | Real screenshots from my terminal runs |
| `slides/` | Our presentation deck: `MGT6078_Group5_Presentation.pdf` |
| `report/` | Our final report: `MGT6078_Group5_Final_Report.pdf` (Dec 15, 2026) |
| `code/alpaca_news_pull.py` | Point-in-time news headlines from the Alpaca News API |
| `code/alpaca_price_pull.py` | Daily prices, strategy returns and short-sale availability from Alpaca |
| `code/fnspid_filter.py` | FNSPID news filtered to the paper's Oct 2021 – Dec 2023 window |
| `code/factor_data_pull.py` | Fama-French, momentum, reversal, q5 factors and VIX |

## Data (all free, $0 total)

I wanted anyone to be able to rebuild our dataset, so we only used free sources: Alpaca News and Market Data APIs, FNSPID (Hugging Face), the Ken French Data Library, global-q.org, FRED and SEC EDGAR.

The raw data files aren't committed because they're large. The scripts in `code/` rebuild them.

### Let's run it

```bash
python -m venv newsenv
source newsenv/bin/activate
pip install requests pandas pandas_market_calendars

export APCA_API_KEY_ID="your_key_id"
export APCA_API_SECRET_KEY="your_secret_key"

python code/factor_data_pull.py
python code/alpaca_news_pull.py --start 2026-04-01 --end 2026-11-18
python code/alpaca_price_pull.py --panels alpaca_news_output/alpaca_news_panel.csv --start 2026-03-15 --end 2026-11-18 --label 2026
```

Honestly, the hardest part wasn't the model. It was making sure every headline only counts from the moment a real investor could have traded on it, so there's zero look-ahead bias.

## Team (Group 5)

Anay Abhijit Joshi, Eriore Adeoluwa, Immanuella Akumabor, Himanshu Bhatt, Dikshita Chalke, Adeola H Fasola, Qianye Lin

*Finally, a note: this is an educational research project. Nothing here is investment advice.*

![Profile Views](https://komarev.com/ghpvc/?username=anay-a-joshi&color=green)  
