import json
import re
import sys
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; company-profile-lite/1.0)"
}

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{8,}\d)(?!\w)")

LOCATION_HINTS = [
    "new york", "san francisco", "london", "paris", "madrid", "barcelona",
    "berlin", "dubai", "riyadh", "singapore", "toronto", "sydney",
    "spain", "france", "germany", "uk", "united kingdom", "usa",
    "united states", "canada", "saudi arabia", "uae", "morocco",
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


def soup_from_url(url: str):
    try:
        html = fetch_html(url)
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_meta_content(soup: BeautifulSoup, *attrs):
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


def extract_emails(text: str):
    return sorted(set(EMAIL_RE.findall(text)))[:10]


def normalize_phone(phone: str) -> str:
    phone = unquote(phone)
    phone = phone.replace("tel:", "").replace("telephone:", "")
    phone = re.sub(r"[^\d+().\-\s]", "", phone)
    return clean_text(phone).strip(" -.")


def looks_like_dateish(cleaned: str, digits: str) -> bool:
    parts = [p for p in re.split(r"[\s\-/.()]+", cleaned) if p]

    if re.fullmatch(r"(19|20)\d{2}", digits):
        return True

    if re.fullmatch(r"(19|20)\d{2}(19|20)\d{2}", digits):
        return True

    if len(parts) >= 3:
        if (
            re.fullmatch(r"(19|20)\d{2}", parts[0])
            and re.fullmatch(r"(0?[1-9]|1[0-2])", parts[1])
            and re.fullmatch(r"(0?[1-9]|[12]\d|3[01])", parts[2])
        ):
            return True

    if len(parts) >= 4:
        if (
            re.fullmatch(r"(19|20)\d{2}", parts[0])
            and re.fullmatch(r"(19|20)\d{2}", parts[1])
            and re.fullmatch(r"(0?[1-9]|1[0-2])", parts[2])
            and re.fullmatch(r"(0?[1-9]|[12]\d|3[01])", parts[3])
        ):
            return True

    group_lengths = tuple(len(p) for p in parts if p.isdigit())
    if group_lengths in {(4, 2, 2), (4, 4), (4, 4, 2), (4, 4, 2, 2)}:
        if any(re.fullmatch(r"(19|20)\d{2}", p) for p in parts):
            return True

    return False


def extract_phones_from_text(text: str):
    raw = PHONE_RE.findall(text)
    phones = []
    seen = set()

    for phone in raw:
        cleaned = normalize_phone(phone)
        digits = re.sub(r"\D", "", cleaned)

        if len(digits) < 10 or len(digits) > 15:
            continue

        if looks_like_dateish(cleaned, digits):
            continue

        formatting_signals = (
            "+" in cleaned
            or "(" in cleaned
            or ")" in cleaned
            or cleaned.count(" ") >= 2
            or cleaned.count("-") >= 2
            or cleaned.count(".") >= 2
        )
        if not formatting_signals:
            continue

        if cleaned not in seen:
            seen.add(cleaned)
            phones.append(cleaned)

    return phones[:10]


def extract_tel_links(soup: BeautifulSoup):
    phones = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            cleaned = normalize_phone(href)
            digits = re.sub(r"\D", "", cleaned)
            if 10 <= len(digits) <= 15 and cleaned not in seen:
                seen.add(cleaned)
                phones.append(cleaned)

    return phones[:10]


def extract_socials(soup: BeautifulSoup):
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


def extract_candidate_pages(base_url: str, soup: BeautifulSoup):
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


def find_locations(text: str):
    text_lower = text.lower()
    found = []

    for hint in LOCATION_HINTS:
        if hint in text_lower:
            found.append(hint.title())

    return sorted(set(found))[:10]


def extract_text_from_soup(soup: BeautifulSoup) -> str:
    return clean_text(soup.get_text(" ", strip=True))


def merge_unique(existing, new_values):
    seen = set(existing)
    for value in new_values:
        if value not in seen:
            existing.append(value)
            seen.add(value)
    return existing


def extract_company_profile(url: str):
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
    phones = extract_tel_links(homepage_soup)

    for extra_url in extract_candidate_pages(url, homepage_soup):
        extra_soup = soup_from_url(extra_url)
        if extra_soup is None:
            continue

        combined_text_parts.append(extract_text_from_soup(extra_soup))
        merge_unique(phones, extract_tel_links(extra_soup))

        extra_socials = extract_socials(extra_soup)
        for key, value in extra_socials.items():
            socials.setdefault(key, value)

    combined_text = " ".join(combined_text_parts)

    if not phones:
        phones = extract_phones_from_text(combined_text)

    return {
        "url": url,
        "company_name": guess_company_name(homepage_soup, domain),
        "description": guess_description(homepage_soup),
        "emails": extract_emails(combined_text),
        "phones": phones[:10],
        "socials": socials,
        "locations": find_locations(combined_text),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python main.py "https://example.com"')
        sys.exit(1)

    profile = extract_company_profile(sys.argv[1])
    print(json.dumps(profile, indent=2, ensure_ascii=False))
