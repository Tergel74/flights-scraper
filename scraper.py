import asyncio
from playwright.async_api import async_playwright
import os
import re
import requests
from supabase import create_client, Client
from datetime import datetime
# from dotenv import load_dotenv
from bs4 import BeautifulSoup

# load_dotenv(override=True)

# SUPABASE_URL = os.getenv("SUPABASE_URL")
# SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
# TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)

DEPART_DATES = ["2026-12-20", "2026-12-24", "2026-02-27"]


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


def check_price_drop(current_flights: list, route: str = "ICN-NRT-UBN-ICN"):
    if not current_flights:
        return

    cheapest_flight = min(
        [flight for flight in current_flights], key=lambda x: x.get("price_amount", float("inf"))
    )
    current_cheapest_price = int(cheapest_flight.get("price_amount", 0))
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Extract legs and metadata
    legs = cheapest_flight.get("legs", [])
    has_baggage = "🧳 Baggage Included" if cheapest_flight.get(
        "includes_baggage") else "❌ No Baggage"
    has_meal = "🍱 Meal Included" if cheapest_flight.get(
        "includes_meal") else "❌ No Meal"

    try:
        resp = (
            supabase.table("flight_itineraries")
            .select("price_amount")
            .order("price_amount", desc=False)
            .limit(1)
            .execute()
        )

        lowest = int(resp.data[0]["price_amount"]) if resp.data else None

        leg_lines = []
        for i, leg in enumerate(legs, 1):
            orig = leg.get("origin", {})
            dest = leg.get("destination", {})
            leg_lines.append(
                f"  *Leg {i}:* {orig.get('code')} ➔ {dest.get('code')} ({leg.get('airline')})\n"
                f"    └ 🛫 {orig.get('date')} {orig.get('time')} ➔ 🛬 {dest.get('date')} {dest.get('time')}"
            )
        legs_formatted = "\n".join(leg_lines)

        if lowest is None or current_cheapest_price < lowest:
            diff_text = ""
            if lowest:
                savings = lowest - current_cheapest_price
                diff_text = f"\n📉 *Price Drop:* -{savings:,} MNT lower than previous minimum!"

            msg = (
                f"🔥 *NEW HISTORIC LOW ALERT!* ({route})\n"
                f"⏰ *Checked:* {current_date}\n\n"
                f"💰 *Price:* {current_cheapest_price:,} MNT{diff_text}\n"
                f"ℹ️ {has_baggage} | {has_meal}\n\n"
                f"✈️ *Itinerary Breakdown:*\n{legs_formatted}\n\n"
                f"🔗 Check Nisleg.mn to book!"
            )
        else:
            diff = current_cheapest_price - lowest
            msg = (
                f"📊 *DAILY CHEAPEST FLIGHT REPORT* ({route})\n"
                f"⏰ *Checked:* {current_date}\n\n"
                f"💰 *Current Price:* {current_cheapest_price:,} MNT\n"
                f"🏷️ *Historic Low:* {lowest:,} MNT (+{diff:,} MNT)\n"
                f"ℹ️ {has_baggage} | {has_meal}\n\n"
                f"✈️ *Itinerary Breakdown:*\n{legs_formatted}\n\n"
                f"🔗 Check Nisleg.mn to book!"
            )

        send_telegram_alert(msg)

    except Exception as e:
        print(f"❌ Error checking price drop: {e}")


def clean_price(price_str: str) -> int:
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else 0


def is_morning_flight(time_str: str, start_hour: int = 7, end_hour: int = 10) -> bool:
    """Checks if HH:MM time string falls between start_hour and end_hour."""
    try:
        hours, minutes = map(int, time_str.strip().split(":"))
        time_in_minutes = hours * 60 + minutes
        return (start_hour * 60) <= time_in_minutes <= (end_hour * 60)
    except Exception:
        return False


def matches_time_criteria(flight_data: dict) -> bool:
    """Ensures Seoul (ICN) departure and UB (UBN) -> Seoul (ICN) return are both 07:00-10:00."""
    legs = flight_data.get("legs", [])

    icn_morning = False
    ubn_to_icn_morning = False

    for leg in legs:
        origin_code = leg.get("origin", {}).get("code", "").upper()
        dest_code = leg.get("destination", {}).get("code", "").upper()
        dep_time = leg.get("origin", {}).get("time", "")

        if origin_code == "ICN":
            if is_morning_flight(dep_time, 7, 10):
                icn_morning = True

        if origin_code == "UBN" and dest_code == "ICN":
            if is_morning_flight(dep_time, 7, 10):
                ubn_to_icn_morning = True

    return icn_morning and ubn_to_icn_morning


def save_flight_itinerary(flight_data: dict):
    try:
        response = (
            supabase.table("flight_itineraries")
            .insert({
                "price_amount": flight_data["price_amount"],
                "price_currency": flight_data["price_currency"],
                "tags": flight_data["tags"],
                "includes_baggage": flight_data["includes_baggage"],
                "includes_meal": flight_data["includes_meal"],
                # Python dict/list is automatically serialized to JSONB
                "legs": flight_data["legs"],
            })
            .execute()
        )

        return response.data
    except Exception as e:
        print(f"Error saving to Supabase: {e}")
        return None


def parse_flight_card(html_content: str) -> dict:
    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Parse each flight leg row
    leg_rows = soup.find_all(
        "div", class_=lambda c: c and "px-6" in c and "py-4" in c
    )
    legs = []

    for leg in leg_rows:
        airline_el = leg.find(
            "div", class_=lambda c: c and "font-bold" in c and "text-xs" in c
        )
        flight_num_el = leg.find(
            "div", class_=lambda c: c and "text-[10px]" in c
        )

        # Location containers: [0] = Origin, [1] = Duration Line, [2] = Destination
        loc_blocks = leg.find_all(
            "div", recursive=False
        )[1].find_all("div", recursive=False)

        def extract_location(block):
            flex_col = block.find(
                "div", class_=lambda c: c and "flex-col" in c)
            code_el = flex_col.find(
                "span", class_=lambda c: c and "text-base" in c
            ) if flex_col else None
            city_el = flex_col.find(
                "span", class_=lambda c: c and "text-xs" in c
            ) if flex_col else None
            time_el = block.find(
                "div", class_=lambda c: c and "text-base" in c and "font-bold" in c
            )
            date_el = block.find(
                "div", class_=lambda c: c and "text-[11px]" in c and "mt-0.5" in c
            )

            return {
                "code": code_el.get_text(strip=True) if code_el else "",
                "city": city_el.get_text(strip=True) if city_el else "",
                "time": time_el.get_text(strip=True) if time_el else "",
                "date": date_el.get_text(strip=True) if date_el else "",
            }

        duration_el = leg.find(
            "div", class_=lambda c: c and "text-[11px]" in c and "font-semibold" in c
        )

        legs.append({
            "airline": airline_el.get_text(strip=True) if airline_el else "",
            "flight_number": flight_num_el.get_text(strip=True) if flight_num_el else "",
            "duration": duration_el.get_text(strip=True) if duration_el else "",
            "origin": extract_location(loc_blocks[0]),
            "destination": extract_location(loc_blocks[2]),
        })

    # 2. Extract Price & Currency
    price_el = soup.find(
        "div", class_=lambda c: c and "text-xl" in c and "font-bold" in c
    )
    price_amount = 0.0
    price_currency = "MNT"

    if price_el:
        price_text = price_el.get_text(strip=True)  # e.g. "2,563,600 MNT"
        parts = price_text.split(" ")
        if len(parts) >= 2:
            price_amount = float(parts[0].replace(",", ""))
            price_currency = parts[1]

    # 3. Extract Tags (Baggage, Meals, Multi-city)
    tag_spans = soup.find_all(
        "span", class_=lambda c: c and "text-[11px]" in c)
    tags = [t.get_text(strip=True)
            for t in tag_spans if t.get_text(strip=True)]

    return {
        "price_amount": price_amount,
        "price_currency": price_currency,
        "tags": tags,
        "includes_baggage": any("Ачаатай" in t for t in tags),
        "includes_meal": any("Хоолтой" in t for t in tags),
        "legs": legs,
    }


async def scrape_flight(page, depart_dates):
    url = f"https://www.nisleg.mn/en"

    try:
        await page.goto(url, wait_until="networkidle", timeout=100000)

        type_button = page.get_by_role(
            "combobox").filter(has_text="Round-trip")
        await type_button.click()
        multi_city_button = page.get_by_role("option", name="Multi-city")
        await multi_city_button.click()

        from_button = page.locator("#options-menu").filter(has_text="From")
        await from_button.click()
        await page.get_by_role("button").and_(page.get_by_title("Seoul Incheon International Airport")).click()

        to_button = page.locator("#options-menu").filter(has_text="To")
        await to_button.click()
        await page.get_by_role("button").and_(page.get_by_title("Tokyo Narita International Airport")).click()

        departure_button = page.get_by_role(
            "button", name="Departure", exact=True)
        await departure_button.click()

        next_month_btn = page.get_by_role("button", name="Go to next month")
        await next_month_btn.click()
        await next_month_btn.click()

        december_month = page.locator(
            ".rdp-caption_end").filter(has_text="December 2026")
        await december_month.locator("button[name='day']").get_by_text(depart_dates[0][-2:], exact=True).click()

        add_flight_button = page.locator(
            "button").filter(has_text="Add flight")
        await add_flight_button.click()

        # from_button2 = page.locator(
        #     "#options-menu").filter(has_text="From").nth(1)
        # await from_button2.click()
        # await page.get_by_role("button").and_(page.get_by_title("Tokyo Narita International Airport")).click()

        to_button2 = page.locator("button[title='To']").first
        await to_button2.click()
        await page.get_by_role("button").and_(page.get_by_title("Ulaanbaatar Chinggis Khaan International Airport")).click()

        departure_button2 = page.get_by_role(
            "button", name="Departure", exact=True)
        await departure_button2.click()

        december_month = page.locator(
            ".rdp-caption_start").filter(has_text="December 2026")
        await december_month.locator("button[name='day']").get_by_text(depart_dates[1][-2:], exact=True).click()

        add_flight_button = page.locator(
            "button").filter(has_text="Add flight")
        await add_flight_button.click()

        # from_button3 = page.locator(
        #     "#options-menu").filter(has_text="From").nth(2)
        # await from_button3.click()
        # await page.get_by_role("button").and_(page.get_by_title("Ulaanbaatar Chinggis Khaan International Airport")).click()

        to_button3 = page.locator("button[title='To']").first
        await to_button3.click()
        await page.get_by_role("button").and_(page.get_by_title("Seoul Incheon International Airport")).click()

        departure_button3 = page.get_by_role(
            "button", name="Departure", exact=True)
        await departure_button3.click()

        next_month_btn = page.get_by_role("button", name="Go to next month")
        await next_month_btn.click()

        feb_month = page.locator(
            ".rdp-caption_end").filter(has_text="February 2027")
        await feb_month.locator("button[name='day']").get_by_text(depart_dates[2][-2:], exact=True).click()

        search_button = page.get_by_role("button", name="Search", exact=True)
        await search_button.click()

        await page.wait_for_selector("div[id^='result_content_']", timeout=15000)

        all_cards = await page.locator("div[id^='result_content_']").all()
        flight_results = []

        for card in all_cards:
            card_html = await card.inner_html()
            data = parse_flight_card(card_html)

            if not data:
                continue

            if matches_time_criteria(data):
                save_flight_itinerary(data)
                flight_results.append(data)

        return flight_results

    except Exception as e:
        print(
            f"Could not load results for {depart_dates}: {e}")
        return []


async def main():
    async with async_playwright() as p:
        # channel="chrome" bypasses binary download by using installed Google Chrome
        browser = await p.chromium.launch(
            headless=True
            # headless=False,
            # channel="chrome"
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        records = await scrape_flight(page, DEPART_DATES)
        # await scrape_flight(page, dep, ret)
        await asyncio.sleep(2)

        await browser.close()

        check_price_drop(records)

if __name__ == "__main__":
    asyncio.run(main())
