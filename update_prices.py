#!/usr/bin/env python3
"""Floor Watch weekly price updater. Reads card data straight out of
index.html (single source of truth, no duplicated data to drift out of
sync), attempts a safe price refresh per card via price_helper, and
writes a full audit trail into the page as an HTML comment."""
import re
import time
from datetime import datetime, timezone, timedelta
from price_helper import build_url, fetch, validate_and_extract, bounds_check

CARD_RE = re.compile(
    r'name:\s*"((?:[^"\\]|\\.)+)",\s*set:\s*"((?:[^"\\]|\\.)+)",\s*era:\s*"[^"]+",\s*\n'
    r'\s*rarity:\s*"[^"]+",\s*num:\s*"((?:[^"\\]|\\.)+)",\s*\n'
    r'\s*peak:\s*(?:[\d.]+|null),\s*floor:\s*(?:[\d.]+|null),\s*current:\s*([\d.]+|null)'
)


def unescape(s):
    return s.replace('\\u2014', '—').replace('\\u2019', '’').replace('\\"', '"')


def main():
    with open("index.html", encoding="utf-8") as f:
        html = f.read()

    matches = list(CARD_RE.finditer(html))
    print(f"Found {len(matches)} tracked cards")

    log_lines = []
    updated = 0

    for m in matches:
        name = unescape(m.group(1))
        try:
            set_name = unescape(m.group(2))
            num = m.group(3)
            old_current_str = m.group(4)
            old_current = None if old_current_str == "null" else float(old_current_str)

            url = build_url(name, set_name, num)
            if not url:
                log_lines.append(f"{name}: SKIP (no card number to build URL from)")
                continue

            html_page = fetch(url)
            time.sleep(1)  # be a polite scraper, not a hammer
            new_price, reason = validate_and_extract(html_page, name)

            if new_price is None:
                log_lines.append(f"{name}: SKIP ({reason})")
                continue

            if not bounds_check(new_price, old_current):
                log_lines.append(
                    f"{name}: REJECT (${new_price} vs last known ${old_current} -- outside safe bounds, likely wrong-card match)"
                )
                continue

            # Safe to apply. Replace only THIS card's current value, anchored
            # on its exact name+set+num so we never touch a different card
            # that happens to share the same price.
            price_str = str(int(new_price)) if new_price == int(new_price) else str(new_price)
            old_block = m.group(0)
            new_block = old_block[:old_block.rfind("current:")] + f"current: {price_str}"
            html = html.replace(old_block, new_block, 1)
            updated += 1
            log_lines.append(f"{name}: UPDATED ${old_current} -> ${new_price}")
        except Exception as e:
            # A single card's unexpected failure must never take down the
            # other 28 -- log it and keep going.
            log_lines.append(f"{name}: SKIP (unexpected error: {type(e).__name__}: {e})")
            continue

    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M PHT")
    comment = (
        f"<!-- PRICE_UPDATE_LOG [{stamp}]: {updated}/{len(matches)} cards updated\n"
        + "\n".join(log_lines) + "\n-->"
    )
    if "<!-- PRICE_UPDATE_LOG" in html:
        html = re.sub(r"<!-- PRICE_UPDATE_LOG.*?-->", comment, html, count=1, flags=re.S)
    else:
        html = html.replace("<head>", "<head>\n" + comment, 1)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Done. {updated}/{len(matches)} cards updated.")
    print("\n".join(log_lines))


if __name__ == "__main__":
    main()
