# Purpose of this agent
First and foremost I am doing this to learn about agentic AI workflows and how to build agents in python. As the business landscape progressively moves toward agentic workflows, I belive understanding safe implementation of them is vital. While this agent may not seem all that different from a normal chat with an LLM, I am doing this to showcase the principles that building agents in python promotes.

1) **Grainular and Controlled Tooling:** We as developers are able to build gaurdrails and validation steps into agents. In this example, when the agent pulls news, we can trace exactly how and where that news came from. The agent is less likely to haullicinatte news that never happened, as it is summarizing verified sources and returning that summary. This builds saftey into output.

2) **Exogenous Platform Design:** While here I did not provide an interface for this agent, this code could be packaged into a platform outside of the main Anthropic or OpenAI chat bot interfaces. We can take the brains of the models, give them arms through tooling, and then package them into new and unique software interfaces.

3) **Exogenous Tooling:** As developers, we can now take AI tooling into our own hands. Allowing us to push the limits of AI problem solving without waiting for large companies to keep up

Ultimately it is about risk control and ease of use. Building agents in python offers greater control and can thereby


# Setup

1. Create a virtual environment and install dependencies:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Create a `.env` file in the project root with:
   ```
   EMAIL_ADDRESS=your_gmail_address@gmail.com
   EMAIL_APP_PASSWORD=your_16_char_app_password
   RECIPIENT_EMAIL=where_the_newsletter_should_go@example.com
   PORTFOLIO_PATH=portfolio.csv
   ```
   `EMAIL_APP_PASSWORD` must be a Gmail **App Password**, not your normal login password
   (Google Account -> Security -> 2-Step Verification -> App passwords). Gmail rejects
   SMTP login with a regular password. `PORTFOLIO_PATH` is optional and defaults to
   `portfolio.csv` if omitted.
3. Run the agent:
   ```
   python main.py
   ```
   It will prompt you for a question/instruction in the terminal.

# How the portfolio CSV works

`get_stock_quantity` reads holdings from the CSV at `PORTFOLIO_PATH` (default
`portfolio.csv`, gitignored since it holds real financial data). It only requires two
columns, matched by header name: `Ticker` and `Shares`. Any other columns (e.g. cost
basis, dividends received) are ignored, so you can point it at a raw Robinhood
"positions" export as-is.

If you only have Robinhood **transaction history** (not a positions export), use
`parse_portfolio()` to derive share counts from it:
```python
from main import parse_portfolio
parse_portfolio("your_transaction_export.csv", "portfolio.csv")
```
It sums `Quantity` across `Buy`/`SDIV` (stock dividend) rows and subtracts `Sell` rows,
per ticker (`Instrument` column). Cash-only rows (`CDIV`, `DTAX`, `DCF`, `MISC`, `SLIP`,
`ITRF`, `FUTSWP`) are ignored since they carry no share quantity. Positions that net out
to ~0 (fully sold) are dropped from the output.

`example_transactions.csv` is a small fabricated transaction export you can try this
against — it isn't anyone's real data, just enough rows to exercise the Buy/Sell/
dividend/tax-code handling described above:
```python
from main import parse_portfolio
parse_portfolio("example_transactions.csv", "portfolio.csv")
```
This produces `AAPL: 10` and `MSFT: 3.5` shares. It also includes a TSLA position that's
bought and then fully sold, demonstrating that fully-exited positions are dropped
rather than showing up as `0`.

# Tools

| Tool | Input | Output | Notes |
|---|---|---|---|
| `get_stock_prices` | `tickers_to_query: list[str]` | `dict[str, float \| None]` | Live prices via `yfinance`. Unresolvable tickers map to `None` instead of failing the whole batch. |
| `get_stock_quantity` | `tickers_to_query: list[str]` | `dict[str, float \| None]` | Reads `PORTFOLIO_PATH`. Tickers not in the portfolio map to `None`. |
| `pull_news` | `tickers_to_query: list[str]` | `dict[str, list[str]]` | Each ticker maps to a list of `"Title (Publisher): Summary"` text blurbs via `yfinance`. |
| `write_email` | `subject: str`, `body: str` | `None` | Sends via Gmail SMTP to the fixed `RECIPIENT_EMAIL`. Raises `RuntimeError` if credentials aren't configured. |

All four are batched/list-based where relevant (prices, quantities, news) so the agent
can resolve an entire portfolio in one tool call instead of one call per ticker —
this matters because each additional tool call costs a full extra round trip through
the model, not just the underlying API request.

`portfolio_path` and the email recipient are intentionally **not** exposed as
parameters on `get_stock_quantity`/`write_email` — they're fixed configuration for a
single-user script, sourced from `PORTFOLIO_PATH`/`RECIPIENT_EMAIL` at the top of
`main.py`. Keeping them out of the tool signatures means the agent has nothing to ask
about and can't second-guess them.
