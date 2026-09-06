import asyncio
from playwright.async_api import async_playwright
import pandas as pd

DEPART_DATES = ["2026-12-19"]
# DEPART_DATES = ["2026-12-19", "2026-12-20"]
RETURN_DATES = ["2027-02-25"]
# RETURN_DATES = ["2027-02-25", "2027-02-26",
#                 "2027-02-27", "2027-02-28"]


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
        return flight_results

    except Exception as e:
        print(
            f"Could not load results for {depart_date} to {return_date}: {e}")
        return []


async def main():
    async with async_playwright() as p:
        # channel="chrome" bypasses binary download by using installed Google Chrome
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome"
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        all_records = []

        for dep in DEPART_DATES:
            for ret in RETURN_DATES:
                records = await scrape_flight(page, dep, ret)
                all_records.append(records)
                await asyncio.sleep(2)

        await browser.close()

        if all_records:
            df = pd.DataFrame(
                [record for records in all_records for record in records])
            print("\nScraping Complete! Results Summary:")
            print(df.to_string(index=False))
            df.to_csv("flight_prices.csv", index=False)
            print("\nSaved results to flight_prices.csv")
        else:
            print("\nNo flight records extracted.")

if __name__ == "__main__":
    asyncio.run(main())
