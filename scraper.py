import asyncio
from playwright.async_api import async_playwright
# import pandas as pd
import os
import re
import requests
from supabase import create_client, Client
# from dotenv import load_dotenv

# load_dotenv(override=True)

# SUPABASE_URL = os.getenv("SUPABASE_URL")
# SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)

# DEPART_DATES = ["2026-12-19"]
DEPART_DATES = ["2026-12-19", "2026-12-20"]
# RETURN_DATES = ["2027-02-25"]
RETURN_DATES = ["2027-02-25", "2027-02-26",
                "2027-02-27", "2027-02-28"]


def send_telegram_alert(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token or chat ID missing. Skipping alert.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
        print("Telegram alert sent!")
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")


def check_price_drop(current_flights: list, route: str = "ICN-UBN"):
    if not current_flights:
        return

    cheapest_new = min(
        current_flights, key=lambda x: clean_price(x.get("price", "0")))
    new_price = clean_price(cheapest_new.get("price", "0"))

    try:
        resp = supabase.table("flight_prices").select("price").eq(
            "route", route).order("price", desc=False).limit(1).execute()

        lowest = resp.data[0]["price"] if resp.data else None

        if lowest is None or new_price < lowest:
            ob = cheapest_new.get("outbound", {})
            ib = cheapest_new.get("inbound", {})

            diff_text = ""
            if lowest:
                savings = lowest - new_price
                diff_text = f"\n📉 *Price Drop:* -{savings:,}₮ lower than previous minimum!"

            msg = (
                f"✈️ *PRICE DROP ALERT!* ({route})\n\n"
                f"💰 *New Price:* {cheapest_new.get('price')}{diff_text}\n"
                f"🏢 *Airline:* {ob.get('airline')}\n"
                f"📅 *Outbound:* {ob.get('depart_date')} ({ob.get('depart_time')})\n"
                f"📅 *Inbound:* {ib.get('depart_date')} ({ib.get('depart_time')})\n\n"
                f"🔗 Check Nisleg.mn to book!"
            )
            send_telegram_alert(msg)
    except Exception as e:
        print(f"Error checking price drop: {e}")


def clean_price(price_str: str) -> int:
    digits = re.sub(r'[^\d]', '', price_str)
    return int(digits) if digits else 0


def save_flights_to_supabase(flight_list: list, route: str = "ICN-UBN"):
    records = []

    for f in flight_list:
        ob = f.get("outbound", {})
        ib = f.get("inbound", {})

        record = {
            "route": route,
            "price": clean_price(f.get("price", "0")),
            "currency": "MNT",
            "outbound_airline": ob.get("airline"),
            "outbound_depart_date": ob.get("depart_date"),
            "outbound_depart_time": ob.get("depart_time"),
            "outbound_landing_time": ob.get("landing_time"),
            "inbound_airline": ib.get("airline"),
            "inbound_depart_date": ib.get("depart_date"),
            "inbound_depart_time": ib.get("depart_time"),
            "inbound_landing_time": ib.get("landing_time"),
            "raw_payload": f
        }
        records.append(record)

    if records:
        response = supabase.table("flight_prices").insert(records).execute()
        print(
            f"Successfully inserted {len(records)} flight records into Supabase.")
        return response


async def parse_flight_card(card_locator):
    price_raw = await card_locator.locator("text=/.*₮/").first.inner_text()
    price = price_raw.strip()

    outbound_grid = card_locator.locator("div.grid").nth(0)
    outbound_airline = await outbound_grid.locator("img").first.get_attribute("alt")

    ob_left_block = outbound_grid.locator("div.flex-none").nth(0)
    ob_middle_block = outbound_grid.locator("div.flex-auto.flex-col").first
    ob_right_block = outbound_grid.locator("div.flex-none").last

    ob_depart_time = await ob_left_block.locator("div.text-lg").inner_text()
    ob_depart_date = await ob_left_block.locator("div.text-xs").last.inner_text()
    ob_duration = await ob_middle_block.locator("div").first.inner_text()

    ob_landing_time = await ob_right_block.locator("div.text-lg").inner_text()
    ob_landing_date = await ob_right_block.locator("div.text-xs").last.inner_text()

    inbound_grid = card_locator.locator("div.grid").nth(1)
    inbound_airline = await inbound_grid.locator("img").first.get_attribute("alt")

    ib_left_block = inbound_grid.locator("div.flex-none").nth(0)
    ib_middle_block = inbound_grid.locator("div.flex-auto.flex-col").first
    ib_right_block = inbound_grid.locator("div.flex-none").last

    ib_depart_time = await ib_left_block.locator("div.text-lg").inner_text()
    ib_depart_date = await ib_left_block.locator("div.text-xs").last.inner_text()
    ib_duration = await ib_middle_block.locator("div").first.inner_text()

    ib_landing_time = await ib_right_block.locator("div.text-lg").inner_text()
    ib_landing_date = await ib_right_block.locator("div.text-xs").last.inner_text()

    return {
        "price": price,
        "outbound": {
            "airline": outbound_airline or "Unknown",
            "depart_date": ob_depart_date.strip(),
            "depart_time": ob_depart_time.strip(),
            "landing_date": ob_landing_date.strip(),
            "landing_time": ob_landing_time.strip(),
            "duration": ob_duration.strip().replace("\n", " "),
        },
        "inbound": {
            "airline": inbound_airline or "Unknown",
            "depart_date": ib_depart_date.strip(),
            "depart_time": ib_depart_time.strip(),
            "landing_date": ib_landing_date.strip(),
            "landing_time": ib_landing_time.strip(),
            "duration": ib_duration.strip().replace("\n", " "),
        }
    }


async def scrape_flight(page, depart_date, return_date):
    url = f"https://www.nisleg.mn/en"
    print(f"🔎 Checking: {depart_date} ➔ {return_date}...")

    try:
        await page.goto(url, wait_until="networkidle", timeout=100000)
        from_button = page.locator("#options-menu").filter(has_text="From")
        await from_button.click()
        await page.get_by_role("button").and_(page.get_by_title("Seoul Incheon International Airport")).click()

        to_button = page.locator("#options-menu").filter(has_text="To")
        await to_button.click()
        await page.get_by_role("button").and_(page.get_by_title("Ulaanbaatar Chinggis Khaan International Airport")).click()

        await page.get_by_role("button", name="Departure", exact=True).click()

        next_month_btn = page.get_by_role("button", name="Go to next month")
        await next_month_btn.click()
        await next_month_btn.click()

        december_month = page.locator(
            ".rdp-caption_end").filter(has_text="December 2026")
        await december_month.locator("button[name='day']").get_by_text(depart_date[-2:], exact=True).click()
        await next_month_btn.click()
        await next_month_btn.click()

        feb_month = page.locator(
            ".rdp-caption_end").filter(has_text="February 2027")
        await feb_month.locator("button[name='day']").get_by_text(return_date[-2:], exact=True).click()

        search_button = page.get_by_role("button", name="Search", exact=True)
        await search_button.click()

        await page.wait_for_selector("div[id^='result_content_']", timeout=15000)

        cards = (await page.locator("div[id^='result_content_']").all())[:3]
        flight_results = []

        for card in cards:
            data = await parse_flight_card(card)
            flight_results.append(data)

        # print(flight_results[0])

        check_price_drop(flight_results, route="ICN-UBN")

        save_flights_to_supabase(flight_results, route="ICN-UBN")
        # return flight_results

    except Exception as e:
        print(
            f"Could not load results for {depart_date} to {return_date}: {e}")
        return []


async def main():
    async with async_playwright() as p:
        # channel="chrome" bypasses binary download by using installed Google Chrome
        browser = await p.chromium.launch(
            headless=True
            # channel="chrome"
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # all_records = []

        for dep in DEPART_DATES:
            for ret in RETURN_DATES:
                # records = await scrape_flight(page, dep, ret)
                await scrape_flight(page, dep, ret)
                # all_records.append(records)
                await asyncio.sleep(2)

        await browser.close()

        # if all_records:
        #     df = pd.DataFrame(
        #         [record for records in all_records for record in records])
        #     print("\nScraping Complete! Results Summary:")
        #     print(df.to_string(index=False))
        #     df.to_csv("flight_prices.csv", index=False)
        #     print("\nSaved results to flight_prices.csv")
        # else:
        #     print("\nNo flight records extracted.")

if __name__ == "__main__":
    asyncio.run(main())
