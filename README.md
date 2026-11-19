# LLM News Alpha

**Does the ChatGPT news alpha survive publication and mass LLM adoption?**

Group 5's final project for MGT 6078 Finance and Investments, Georgia Institute of Technology, Fall 2026.
It extends Lopez-Lira & Tang (2024), [*Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models*](https://arxiv.org/abs/2304.07619).

Project website: `https://<your-github-username>.github.io/llm-news-alpha/`

## What we add to the paper

| Extension | Question it answers |
|---|---|
| Fresh 2026 test | Did the alpha shrink after the paper was published and LLMs went mainstream? |
| Gemma 3 model-size ladder (1B, 4B, 12B) | Is there a profitability threshold in model size, holding training data fixed? |
| Signal decay and trading costs | How fast does the signal fade, and what is the break-even cost? |
| Risk and cash-flow tests | Does the alpha survive FF3, FF5 and q-factors, and does the score predict earnings surprises? |

## Repository

| Path | Contents |
|---|---|
| `index.html` | Project website (GitHub Pages): Overview, Slides, Report (PDF) |
| `assets/img/` | Screenshots used on the site |
| `slides/` | Presentation deck: `MGT6078_Group5_Presentation.pdf` |
| `report/` | Final report: `MGT6078_Group5_Final_Report.pdf` (Dec 15, 2026) |
| `code/alpaca_news_pull.py` | Point-in-time news headlines from the Alpaca News API |
| `code/alpaca_price_pull.py` | Daily prices, strategy returns and shortability from Alpaca |
| `code/fnspid_filter.py` | FNSPID news filtered to the paper's Oct 2021 to Dec 2023 window |
| `code/factor_data_pull.py` | Fama-French, momentum, reversal, q5 factors and VIX |

## Data (all free)

Alpaca News and Market Data APIs, FNSPID (Hugging Face), Ken French Data Library, global-q.org, FRED and SEC EDGAR.
Raw data files are not committed; the scripts in `code/` rebuild them.

## Team (Group 5)

Eriore Adeoluwa, Immanuella Akumabor, Himanshu Bhatt, Dikshita Chalke, Adeola H Fasola, Anay Abhijit Joshi, Qianye Lin

*Educational research project. Nothing here is investment advice.*
