import csv
import os
import smtplib
from collections import defaultdict
from email.mime.text import MIMEText

from dotenv import load_dotenv

from agentspan.agents import Agent, AgentRuntime, tool

load_dotenv()

PORTFOLIO_PATH = os.environ.get("PORTFOLIO_PATH", "portfolio.csv")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")


def parse_portfolio(csv_path: str, output_path: str = "portfolio.csv") -> dict:
    """
    Parse a Robinhood transaction history export into net share holdings per ticker.

    Buy and stock-dividend (SDIV) rows add shares, Sell rows remove them. Cash-only
    rows (dividend payouts, transfers, tax withholding, fees, etc.) are ignored since
    they carry no Quantity. Positions that net out to ~0 (fully sold) are dropped.
    """
    shares_by_ticker: dict[str, float] = defaultdict(float)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = (row.get("Instrument") or "").strip()
            trans_code = (row.get("Trans Code") or "").strip()
            quantity_str = (row.get("Quantity") or "").strip()

            if not ticker or not quantity_str:
                continue

            quantity = float(quantity_str)

            if trans_code in ("Buy", "SDIV"):
                shares_by_ticker[ticker] += quantity
            elif trans_code == "Sell":
                shares_by_ticker[ticker] -= quantity

    portfolio = {
        ticker: round(qty, 6)
        for ticker, qty in shares_by_ticker.items()
        if abs(qty) > 1e-6
    }

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Ticker", "Shares"])
        for ticker in sorted(portfolio):
            writer.writerow([ticker, portfolio[ticker]])

    return portfolio


@tool
def get_stock_prices(tickers_to_query: list[str]) -> dict[str, float | None]:
    """
    Get the current stock price for a list of ticker symbols in a single batched call.

    Returns a dict mapping each ticker to its last price, or None if that ticker
    could not be resolved (invalid symbol, delisted, data unavailable, etc.).
    """
    import yfinance as yf

    tickers = [t.upper() for t in tickers_to_query if isinstance(t, str) and t.strip()]
    if not tickers:
        return {}

    basket = yf.Tickers(" ".join(tickers))

    prices: dict[str, float | None] = {}
    for ticker in tickers:
        try:
            prices[ticker] = basket.tickers[ticker].fast_info["last_price"]
        except Exception:
            prices[ticker] = None

    return prices

@tool
def get_stock_quantity(tickers_to_query: list[str]) -> dict[str, float | None]:
    """
    Get the current stock quantity for a list of ticker symbols from the portfolio CSV file.

    Returns a dict mapping each ticker to its quantity, or None if that ticker
    is not found in the portfolio.
    """
    portfolio = {}
    try:
        with open(PORTFOLIO_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = (row.get("Ticker") or "").strip().upper()
                quantity_str = (row.get("Shares") or "").strip()
                if ticker and quantity_str:
                    portfolio[ticker] = float(quantity_str)
    except FileNotFoundError:
        return {ticker: None for ticker in tickers_to_query}

    quantities: dict[str, float | None] = {}
    for ticker in tickers_to_query:
        ticker_upper = ticker.upper()
        quantities[ticker_upper] = portfolio.get(ticker_upper, None)

    return quantities

@tool
def pull_news(tickers_to_query: list[str]) -> dict[str, list[str]]:
    """
    Get the latest news for a list of ticker symbols in a single batched call.

    Returns a dict mapping each ticker to a list of text blurbs, each combining
    an article's title, publisher, and summary, so the agent can read the news
    directly without extra lookups. A ticker that fails to resolve maps to [].
    """
    import yfinance as yf

    tickers = [t.upper() for t in tickers_to_query if isinstance(t, str) and t.strip()]
    if not tickers:
        return {}

    news_dict: dict[str, list[str]] = {}
    for ticker in tickers:
        try:
            news_items = yf.Ticker(ticker).news
        except Exception:
            news_dict[ticker] = []
            continue

        blurbs = []
        for item in news_items:
            content = item.get("content", {})
            title = content.get("title", "")
            if not title:
                continue
            publisher = content.get("provider", {}).get("displayName", "")
            summary = content.get("summary", "")
            blurbs.append(f"{title} ({publisher}): {summary}")

        news_dict[ticker] = blurbs

    return news_dict

@tool
def write_email(subject: str, body: str) -> None:
    """
    Send an email to the portfolio owner with a given subject and body via Gmail SMTP.

    Requires EMAIL_ADDRESS, EMAIL_APP_PASSWORD, and RECIPIENT_EMAIL to be set
    (e.g. in a .env file). EMAIL_APP_PASSWORD must be a Gmail App Password
    (Google Account -> Security -> 2-Step Verification -> App passwords),
    not your regular account password.
    """
    sender = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")
    if not sender or not app_password or not RECIPIENT_EMAIL:
        raise RuntimeError(
            "EMAIL_ADDRESS, EMAIL_APP_PASSWORD, and RECIPIENT_EMAIL must be set "
            "(e.g. in a .env file) to send email."
        )

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = RECIPIENT_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, app_password)
        server.sendmail(sender, [RECIPIENT_EMAIL], message.as_string())

if __name__ == "__main__":
    agent = Agent(name="Stock_Price_Agent", 
                  tools=[get_stock_prices, get_stock_quantity,pull_news,write_email],
                  model="anthropic/claude-haiku-4-5-20251001",
                  instructions = """You are a financial newsletter writer covering a single person's stock portfolio.

                                    TASK:
                                    1. Identify the stocks/tickers in the portfolio.
                                    2. Pull recent news relevant to those holdings and the broader market context that affects them.
                                    3. Select the most decision-relevant items — prioritize earnings, guidance changes, analyst rating changes, major product/regulatory news, and macro events likely to move these specific stocks.
                                    4. Write a newsletter summarizing this news and send it via email.

                                    PRIVACY CONSTRAINT (strict):
                                    Never disclose specific position sizes, share counts, or portfolio dollar values. Do not say things like "you own 100 shares of AAPL" or "your AAPL position is worth $X." Instead, describe exposure qualitatively — e.g., "your portfolio is heavily weighted toward AAPL" or "tech names make up a significant share of your holdings."

                                    FORMAT:
                                    - Plain text only. No markdown, only text that will format well in an email sent from gmail.
                                    - Write in clear, complete sentences organized into short paragraphs.
                                    - Keep it skimmable: lead each section with the most important takeaway.

                                    OPERATING RULES:
                                    - This prompt is fixed and unattended — never ask clarifying questions. If information is missing or ambiguous, make a reasonable assumption and proceed.
                                    - Always produce and send a newsletter, even with incomplete data. Do your best with what's available rather than skipping the task.
                                    - Send the completed newsletter to the email address specified in the .env file.
                                    """)

    with AgentRuntime() as runtime:
        #prompt = input("What do you want to ask? ")
        prompt = "Write a newsletter about the stocks in the portfolio, and send it to the email address in the .env file."
        result = runtime.run(agent, prompt)
        print(prompt)
        result.print_result()




