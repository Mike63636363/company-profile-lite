import json
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; company-profile-lite/1.0)"
}

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

# Require phone-like chunks with enough separators/spaces to avoid year ranges.
PHONE_RE = re.compile(
    r"(?<!\w)(\+?\d[\d\s().-]{8,}\d)(?!\w)"
)

LOCATION_HINTS = [
    "new york",
    "san francisco",
    "london",
    "paris",
    "madrid",
    "barcelona",
    "berlin",
    "dubai",
    "riyadh",
    "singapore",
    "toronto",
    "sydney",
    "spain",
    "france",
    "germany",
    "uk",
    "united kingdom",
    "usa",
    "united states",
    "canada",
    "saudi arabia",
    "uae",
    "morocco",
]


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=12)
    response.raise_for_status()
    return response.text


def soup_from_url(url: str) -> BeautifulSoup | None:
    try:
        html = fetch_html(url)
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_meta_content(soup: BeautifulSoup, *attrs: tuple[str, str]) -> str | None:
    for attr_name, attr_value in attrs:
        tag = soup.find("meta", attrs={attr_name: attr_value})
        if tag and tag.get("content"):
            return clean_text(tag["content"])
    return None


def guess_company_name(soup: BeautifulSoup, domain: str) -> str:
    og_name = get_meta_content(soup, ("property", "og:site_name"))
    if og_name:
        return og_name

    if soup.title and soup.title.string:
        title = clean_text(soup.title.string)
        for sep in ["|", "-", "–", "—", ":"]:
            if sep in title:
                left = clean_text(title.split(sep)[0])
                if left:
                    return left
        return title

    return domain.replace("www.", "").split(".")[0].replace("-", " ").title()


def guess_description(soup: BeautifulSoup) -> str:
    meta_desc = get_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
    )
    if meta_desc:
        return meta_desc

    for tag_name in ["h1", "h2", "p"]:
        tag = soup.find(tag_name)
        if tag:
            text = clean_text(tag.get_text(" ", strip=True))
            if len(text) > 40:
                return text[:240]

    return ""


def extract_emails(text: str) -> list[str]:
    emails = sorted(set(EMAIL_RE.findall(text)))
    return emails[:10]


def looks_like_year_or_range(cleaned: str, digits: str) -> bool:
    if re.fullmatch(r"(19|20)\d{2}", digits):
        return True

    if re.fullmatch(r"(19|20)\d{2}(19|20)\d{2}", digits):
        return True

    if re.fullmatch(r"(19|20)\d{2}\s*[-–—]\s*(19|20)\d{2}", cleaned):
        return True

    return False


def extract_phones(text: str) -> list[str]:
    raw = PHONE_RE.findall(text)
    phones = []
    seen = set()

    for phone in raw:
        cleaned = clean_text(phone)
        digits = re.sub(r"\D", "", cleaned)

        if len(digits) < 10 or len(digits) > 15:
            continue

        if looks_like_year_or_range(cleaned, digits):
            continue

        # Require actual phone formatting signals.
        formatting_signals = (
            "+" in cleaned
            or "(" in cleaned
            or ")" in cleaned
            or cleaned.count(" ") >= 1
            or cleaned.count("-") >= 2
            or cleaned.count(".") >= 2
        )
        if not formatting_signals:
            continue

        if cleaned not in seen:
            seen.add(cleaned)
            phones.append(cleaned)

    return phones[:10]


def extract_socials(soup: BeautifulSoup) -> dict[str, str]:
    socials = {}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        href_lower = href.lower()

        if "linkedin.com" in href_lower and "linkedin" not in socials:
            socials["linkedin"] = href
        elif "twitter.com" in href_lower and "twitter" not in socials:
            socials["twitter"] = href
        elif "x.com" in href_lower and "twitter" not in socials:
            socials["twitter"] = href
        elif "facebook.com" in href_lower and "facebook" not in socials:
            socials["facebook"] = href
        elif "instagram.com" in href_lower and "instagram" not in socials:
            socials["instagram"] = href

    return socials


def extract_candidate_pages(base_url: str, soup: BeautifulSoup) -> list[str]:
    candidates = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip().lower()
        if any(x in href for x in ["/about", "/contact", "/company", "/about-us", "/contact-us"]):
            full_url = urljoin(base_url, a["href"])
            if full_url not in seen:
                seen.add(full_url)
                candidates.append(full_url)

    return candidates[:2]


def find_locations(text: str) -> list[str]:
    text_lower = text.lower()
    found = []

    for hint in LOCATION_HINTS:
        if hint in text_lower:
            found.append(hint.title())

    return sorted(set(found))[:10]


def extract_text_from_soup(soup: BeautifulSoup) -> str:
    return clean_text(soup.get_text(" ", strip=True))


def extract_company_profile(url: str) -> dict:
    url = normalize_url(url)
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path

    homepage_soup = soup_from_url(url)
    if homepage_soup is None:
        return {
            "url": url,
            "error": "Could not fetch website",
        }

    combined_text_parts = [extract_text_from_soup(homepage_soup)]
    socials = extract_socials(homepage_soup)

    for extra_url in extract_candidate_pages(url, homepage_soup):
        extra_soup = soup_from_url(extra_url)
        if extra_soup is None:
            continue
        combined_text_parts.append(extract_text_from_soup(extra_soup))
        extra_socials = extract_socials(extra_soup)
        for key, value in extra_socials.items():
            socials.setdefault(key, value)

    combined_text = " ".join(combined_text_parts)

    return {
        "url": url,
        "company_name": guess_company_name(homepage_soup, domain),
        "description": guess_description(homepage_soup),
        "emails": extract_emails(combined_text),
        "phones": extract_phones(combined_text),
        "socials": socials,
        "locations": find_locations(combined_text),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python main.py "https://example.com"')
        sys.exit(1)

    profile = extract_company_profile(sys.argv[1])
    print(json.dumps(profile, indent=2, ensure_ascii=False))
