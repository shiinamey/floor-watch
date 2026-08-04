"""Price update helper for Floor Watch. Split into its own file so each
file stays comfortably under the size that pastes reliably in one shot.

Safety design (this matters more than speed here):
1. URL is CONSTRUCTED from the card's own name/set/num, then the fetched
   page is VALIDATED to actually mention that card before any price is
   trusted -- catches wrong-card / cross-referenced-listing mismatches.
2. Only the narrow "Ungraded" price cell is parsed, never the noisy sold-
   listings history further down the page.
3. A bounds-check rejects any price wildly different from the last known
   value (catches residual mismatches that slip past validation).
4. Only the `current` field is ever touched. peak/floor/verdict/notes
   require human judgment and are never auto-rewritten.
5. Every attempt (success, skip, reject, and why) is logged into an HTML
   comment on the deployed page -- nothing updates silently.
"""
import re
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FloorWatchBot/1.0)"}
TIMEOUT = 20
BOUNDS_MIN = 0.2   # reject if new price < 20% of last known
BOUNDS_MAX = 5.0   # reject if new price > 500% of last known


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9&\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text


def build_url(name, set_name, num):
    # Strip parenthetical/subset qualifiers ("(base set)", "· Galarian
    # Gallery") that don't match PriceCharting's own catalog naming.
    base_set = re.split(r"\s*[\(\u00b7\u2014]", set_name)[0].strip()
    clean_name = re.sub(r"\s*[\u2014-]\s*(Full Art|Alt Art).*$", "", name, flags=re.I)
    clean_name = re.sub(r"[\u2014\u201c\u201d]", "", clean_name).strip()
    numerator = num.split("/")[0] if "/" in num else num
    if not numerator or not numerator.isdigit():
        return None
    set_slug = "pokemon-" + slugify(base_set)
    card_slug = slugify(clean_name) + "-" + numerator
    return f"https://www.pricecharting.com/game/{set_slug}/{card_slug}"


def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        return None


def validate_and_extract(html, name):
    """Returns (ungraded_price, reason) -- price is None if validation
    or extraction failed, with reason explaining why."""
    if html is None:
        return None, "fetch failed"

    # Validate: the card's main name (first word or two, e.g. "Umbreon",
    # "Zekrom") must actually appear near the top of the page. This is
    # the check that catches a constructed URL landing on the wrong
    # product or a 404/redirect page.
    main_name = re.sub(r"\s*(ex|EX|GX|V|VMAX|VSTAR)\s*$", "", name).strip().split()[0]
    head = html[:3000]
    if main_name.lower() not in head.lower():
        return None, f"validation failed: '{main_name}' not found near page top"

    # Extract: find "Ungraded" then the first $X.XX within a short window
    # after it -- matches PriceCharting's summary comparison table, not
    # the sold-listings history further down the page.
    idx = html.find("Ungraded")
    if idx == -1:
        return None, "no 'Ungraded' price table found"
    window = html[idx:idx + 300]
    m = re.search(r"\$([\d,]+\.\d{2})", window)
    if not m:
        return None, "price pattern not found near 'Ungraded'"

    price = float(m.group(1).replace(",", ""))
    return price, "ok"


def bounds_check(new_price, old_price):
    if old_price is None or old_price == 0:
        return True  # nothing to compare against, allow it through
    ratio = new_price / old_price
    return BOUNDS_MIN <= ratio <= BOUNDS_MAX
