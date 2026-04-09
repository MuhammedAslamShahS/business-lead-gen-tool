#!/usr/bin/env python3
"""
Reusable lead collection service for public business data.

This module discovers businesses inside a user-supplied location, enriches them
from public business websites, formats the results, and can serialize them for
API responses or file output.
"""

from __future__ import annotations

import http.client
import json
import re
import ssl
import time
from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
ARCGIS_GEOCODE_URL = (
    "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
    "findAddressCandidates"
)

SOCIAL_PATTERNS = {
    "Facebook": ("facebook.com",),
    "Instagram": ("instagram.com",),
    "LinkedIn": ("linkedin.com",),
    "X/Twitter": ("twitter.com", "x.com"),
    "YouTube": ("youtube.com", "youtu.be"),
}

DIRECTORY_HOSTS = {
    "bbb.org",
    "chamberofcommerce.com",
    "foursquare.com",
    "mapquest.com",
    "manta.com",
    "opentable.com",
    "superpages.com",
    "tripadvisor.com",
    "yellowpages.com",
    "yelp.com",
}

BUSINESS_AMENITIES = {
    "bar",
    "bbq",
    "biergarten",
    "cafe",
    "car_rental",
    "car_repair",
    "car_wash",
    "casino",
    "clinic",
    "dentist",
    "doctors",
    "fast_food",
    "food_court",
    "fuel",
    "gym",
    "ice_cream",
    "marketplace",
    "pharmacy",
    "pub",
    "restaurant",
    "spa",
    "taxi",
    "theatre",
    "veterinary",
}

BUSINESS_TOURISM = {"apartment", "guest_house", "hostel", "hotel", "motel"}
BUSINESS_LEISURE = {"fitness_centre", "sports_centre"}

PHONE_RE = re.compile(r"(?:(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4})")
EMAIL_RE = re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[a-z]{2,}", re.IGNORECASE)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
ADDRESS_JSON_RE = re.compile(r'"address"\s*:\s*(\{.*?\})', re.IGNORECASE | re.DOTALL)

QUERY_BLOCKS = [
    """
    (
      node["name"]["shop"]({bbox});
      way["name"]["shop"]({bbox});
      relation["name"]["shop"]({bbox});
    );
    """,
    """
    (
      node["name"]["office"]({bbox});
      way["name"]["office"]({bbox});
      relation["name"]["office"]({bbox});
    );
    """,
    """
    (
      node["name"]["craft"]({bbox});
      way["name"]["craft"]({bbox});
      relation["name"]["craft"]({bbox});
    );
    """,
    """
    (
      node["name"]["tourism"~"hotel|motel|guest_house|hostel|apartment"]({bbox});
      way["name"]["tourism"~"hotel|motel|guest_house|hostel|apartment"]({bbox});
      relation["name"]["tourism"~"hotel|motel|guest_house|hostel|apartment"]({bbox});
    );
    """,
    """
    (
      node["name"]["leisure"~"fitness_centre|sports_centre"]({bbox});
      way["name"]["leisure"~"fitness_centre|sports_centre"]({bbox});
      relation["name"]["leisure"~"fitness_centre|sports_centre"]({bbox});
    );
    """,
    """
    (
      node["name"]["amenity"~"restaurant|cafe|bar|fast_food|pharmacy|clinic|dentist|doctors|veterinary|marketplace|spa|gym|car_repair|car_wash|fuel"]({bbox});
      way["name"]["amenity"~"restaurant|cafe|bar|fast_food|pharmacy|clinic|dentist|doctors|veterinary|marketplace|spa|gym|car_repair|car_wash|fuel"]({bbox});
      relation["name"]["amenity"~"restaurant|cafe|bar|fast_food|pharmacy|clinic|dentist|doctors|veterinary|marketplace|spa|gym|car_repair|car_wash|fuel"]({bbox});
    );
    """,
]


def build_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


SSL_CONTEXT = build_ssl_context()


@dataclass
class LocationParts:
    country: str = ""
    state: str = ""
    district: str = ""
    city: str = ""

    def cleaned(self) -> "LocationParts":
        return LocationParts(
            country=normalize_text(self.country),
            state=normalize_text(self.state),
            district=normalize_text(self.district),
            city=normalize_text(self.city),
        )

    def to_query_string(self) -> str:
        parts = [self.district, self.city, self.state, self.country]
        cleaned_parts = [normalize_text(part) for part in parts if normalize_text(part)]
        return ", ".join(cleaned_parts)


@dataclass
class LocationQuery:
    original: str
    display_name: str
    country_token: str
    state_token: str
    district_token: str
    city_token: str
    bbox: Tuple[str, str, str, str]
    parts: LocationParts


@dataclass
class Business:
    name: str
    location: str = "Not available"
    phone: str = "Not available"
    email: str = "Not available"
    website: str = "Not available"
    socials: Dict[str, str] = field(
        default_factory=lambda: {
            "Facebook": "Not available",
            "Instagram": "Not available",
            "LinkedIn": "Not available",
            "X/Twitter": "Not available",
            "YouTube": "Not available",
        }
    )
    source_urls: List[str] = field(default_factory=list)
    source_location: str = ""
    dedupe_key: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class LinkParser(HTMLParser):
    """Collect anchor links and lightweight metadata from public HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.links: List[Tuple[str, str]] = []
        self.meta: Dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        if tag == "a":
            href = attr_map.get("href")
            if href:
                self.links.append((href.strip(), (attr_map.get("title") or "").strip()))
        elif tag == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").strip().lower()
            content = (attr_map.get("content") or "").strip()
            if key and content:
                self.meta[key] = content


def http_get(url: str, timeout: int = 20) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def http_post(url: str, data: str, timeout: int = 45) -> str:
    payload = data.encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def safe_get(url: str, timeout: int = 20) -> str:
    try:
        return http_get(url, timeout=timeout)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        ssl.SSLError,
        http.client.HTTPException,
        Exception,
    ):
        return ""


def safe_post(url: str, data: str, timeout: int = 45) -> str:
    try:
        return http_post(url, data=data, timeout=timeout)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        ssl.SSLError,
        http.client.HTTPException,
        Exception,
    ):
        return ""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def normalize_phone(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip(" .,-")
    return cleaned or "Not available"


def normalize_email(value: str) -> str:
    candidate = normalize_text(value).strip().lower()
    return candidate if EMAIL_RE.fullmatch(candidate) else "Not available"


def normalize_url(value: str) -> str:
    if not value:
        return "Not available"
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value.lstrip("/")
    return value


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except ValueError:
        return ""


def is_directory_host(url: str) -> bool:
    host = host_of(url)
    return any(host == entry or host.endswith("." + entry) for entry in DIRECTORY_HOSTS)


def looks_like_business(tags: Dict[str, str]) -> bool:
    if tags.get("shop") and tags.get("name"):
        return True
    if tags.get("office") and tags.get("name"):
        return True
    if tags.get("craft") and tags.get("name"):
        return True
    if tags.get("amenity") in BUSINESS_AMENITIES and tags.get("name"):
        return True
    if tags.get("tourism") in BUSINESS_TOURISM and tags.get("name"):
        return True
    if tags.get("leisure") in BUSINESS_LEISURE and tags.get("name"):
        return True
    return False


def make_dedupe_key(name: str, location: str) -> str:
    raw = f"{name}|{location}".lower()
    return re.sub(r"[^a-z0-9]+", "", raw)


def format_address(tags: Dict[str, str]) -> str:
    if tags.get("addr:full"):
        return normalize_text(tags["addr:full"])

    parts = [
        " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")])),
        tags.get("addr:city"),
        tags.get("addr:state"),
        tags.get("addr:postcode"),
    ]
    cleaned = [normalize_text(part) for part in parts if part and normalize_text(part)]
    return ", ".join(cleaned) if cleaned else "Not available"


def first_nonempty(values: Iterable[Optional[str]]) -> str:
    for value in values:
        if value and normalize_text(value):
            return normalize_text(value)
    return "Not available"


def parse_location_input(location: str) -> LocationParts:
    parts = [normalize_text(part) for part in location.split(",") if normalize_text(part)]
    padded = (parts + ["", "", "", ""])[:4]
    if len(parts) == 1:
        return LocationParts(city=padded[0])
    if len(parts) == 2:
        return LocationParts(city=padded[0], state=padded[1])
    if len(parts) == 3:
        return LocationParts(city=padded[0], state=padded[1], country=padded[2])
    return LocationParts(country=padded[3], state=padded[2], district=padded[0], city=padded[1])


def build_location_parts(
    *,
    country: str = "",
    state: str = "",
    district: str = "",
    city: str = "",
    location: str = "",
) -> LocationParts:
    if any(normalize_text(value) for value in (country, state, district, city)):
        return LocationParts(country=country, state=state, district=district, city=city).cleaned()
    return parse_location_input(location).cleaned()


def geocode_location(location_parts: LocationParts) -> LocationQuery:
    cleaned_parts = location_parts.cleaned()
    cleaned = cleaned_parts.to_query_string()
    if not cleaned:
        raise ValueError("At least one location field is required.")

    query = (
        f"{ARCGIS_GEOCODE_URL}?f=pjson&singleLine={quote_plus(cleaned)}"
        "&maxLocations=1&outFields=Match_addr,City,Region,RegionAbbr"
    )
    payload = safe_get(query, timeout=30)
    if not payload:
        raise ValueError("Could not resolve the requested location.")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Could not parse the requested location.") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("No matching location was found.")

    candidate = candidates[0]
    extent = candidate.get("extent") or {}
    xmin = extent.get("xmin")
    ymin = extent.get("ymin")
    xmax = extent.get("xmax")
    ymax = extent.get("ymax")
    if None in {xmin, ymin, xmax, ymax}:
        raise ValueError("Location bounds were not available for this search.")

    display_name = normalize_text(candidate.get("address", cleaned))
    return LocationQuery(
        original=cleaned,
        display_name=display_name,
        country_token=cleaned_parts.country.lower(),
        state_token=cleaned_parts.state.lower(),
        district_token=cleaned_parts.district.lower(),
        city_token=cleaned_parts.city.lower(),
        bbox=(str(ymin), str(xmin), str(ymax), str(xmax)),
        parts=cleaned_parts,
    )


def overpass_businesses(location_query: LocationQuery, limit: int) -> List[Business]:
    south, west, north, east = location_query.bbox
    bbox = f"{south},{west},{north},{east}"

    seen = set()
    businesses: List[Business] = []
    for block in QUERY_BLOCKS:
        query = f"""
        [out:json][timeout:45];
        {block.format(bbox=bbox)}
        out center tags 150;
        """
        raw = safe_post(OVERPASS_URL, "data=" + quote_plus(query), timeout=80)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for element in data.get("elements", []):
            tags = element.get("tags", {})
            if not looks_like_business(tags):
                continue

            city_value = normalize_text(tags.get("addr:city", ""))
            state_value = normalize_text(tags.get("addr:state", ""))
            country_value = normalize_text(
                first_nonempty([tags.get("addr:country"), tags.get("contact:country"), tags.get("is_in:country")])
            )
            district_values = " ".join(
                filter(
                    None,
                    [
                        normalize_text(tags.get("addr:suburb", "")),
                        normalize_text(tags.get("addr:neighbourhood", "")),
                        normalize_text(tags.get("neighbourhood", "")),
                        normalize_text(tags.get("is_in:suburb", "")),
                    ],
                )
            ).lower()
            if location_query.city_token and city_value and location_query.city_token not in city_value.lower():
                continue
            if location_query.state_token and state_value:
                state_matches = {
                    location_query.state_token,
                    location_query.state_token[:2],
                }
                if state_value.lower() not in state_matches and not any(
                    token == state_value.lower() for token in state_matches
                ):
                    continue
            if location_query.country_token and country_value:
                country_lower = country_value.lower()
                country_parts = {
                    location_query.country_token,
                    location_query.country_token[:2],
                    "".join(part[0] for part in location_query.country_token.split() if part),
                }
                if not any(part and part in country_lower for part in country_parts):
                    continue
            if location_query.district_token and district_values:
                if location_query.district_token not in district_values:
                    continue

            name = normalize_text(tags.get("name", ""))
            if not name:
                continue

            location = format_address(tags)
            key = make_dedupe_key(name, location)
            if key in seen:
                continue
            seen.add(key)

            website = first_nonempty(
                [
                    tags.get("website"),
                    tags.get("contact:website"),
                    tags.get("url"),
                    tags.get("contact:web"),
                ]
            )
            phone = first_nonempty([tags.get("phone"), tags.get("contact:phone")])
            email = first_nonempty([tags.get("email"), tags.get("contact:email")])
            socials = {
                "Facebook": first_nonempty([tags.get("facebook"), tags.get("contact:facebook")]),
                "Instagram": first_nonempty([tags.get("instagram"), tags.get("contact:instagram")]),
                "LinkedIn": first_nonempty([tags.get("linkedin"), tags.get("contact:linkedin")]),
                "X/Twitter": first_nonempty([tags.get("twitter"), tags.get("contact:twitter"), tags.get("x")]),
                "YouTube": first_nonempty([tags.get("youtube"), tags.get("contact:youtube")]),
            }

            businesses.append(
                Business(
                    name=name,
                    location=location,
                    phone=normalize_phone(phone) if phone != "Not available" else phone,
                    email=normalize_email(email) if email != "Not available" else email,
                    website=normalize_url(website) if website != "Not available" else website,
                    socials={
                        label: normalize_url(url) if url != "Not available" else url
                        for label, url in socials.items()
                    },
                    source_location=location_query.display_name,
                    dedupe_key=key,
                )
            )
            if len(businesses) >= max(limit * 3, limit):
                return businesses

    return businesses


def parse_links(html: str) -> Tuple[List[Tuple[str, str]], Dict[str, str]]:
    parser = LinkParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.links, parser.meta


def extract_title(html: str) -> str:
    match = TITLE_RE.search(html)
    return normalize_text(match.group(1)) if match else ""


def extract_emails(text: str) -> List[str]:
    found = []
    for email in EMAIL_RE.findall(text or ""):
        normalized = normalize_email(email)
        if normalized == "Not available":
            continue
        if normalized not in found:
            found.append(normalized)
    return found


def extract_phones(text: str) -> List[str]:
    phones = []
    for phone in PHONE_RE.findall(text or ""):
        normalized = normalize_phone(phone)
        digits = re.sub(r"\D", "", normalized)
        if len(digits) < 10:
            continue
        if len(set(digits)) < 3:
            continue
        if normalized not in phones:
            phones.append(normalized)
    return phones


def extract_social_links(links: Sequence[Tuple[str, str]], base_url: str) -> Dict[str, str]:
    socials = {label: "Not available" for label in SOCIAL_PATTERNS}
    for href, _ in links:
        absolute = normalize_url(urljoin(base_url, href))
        if absolute == "Not available":
            continue
        lowered = absolute.lower()
        if any(token in lowered for token in ("/share", "/sharer", "/intent/", "/dialog/", "/home?status=")):
            continue
        host = host_of(absolute)
        for label, patterns in SOCIAL_PATTERNS.items():
            if socials[label] != "Not available":
                continue
            if any(pattern in host or pattern in lowered for pattern in patterns):
                if "linkedin.com/groups" in lowered:
                    continue
                socials[label] = absolute
    return socials


def extract_contact_links(links: Sequence[Tuple[str, str]]) -> Tuple[List[str], List[str]]:
    phones: List[str] = []
    emails: List[str] = []
    for href, _ in links:
        href = href.strip()
        if href.lower().startswith("tel:"):
            value = normalize_phone(href.split(":", 1)[1])
            digits = re.sub(r"\D", "", value)
            if len(digits) >= 10 and len(set(digits)) >= 3 and value not in phones:
                phones.append(value)
        elif href.lower().startswith("mailto:"):
            value = normalize_email(href.split(":", 1)[1].split("?", 1)[0])
            if value != "Not available" and value not in emails:
                emails.append(value)
    return phones, emails


def likely_contact_page(href: str, base_url: str, website_host: str) -> bool:
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return False
    if host_of(absolute) != website_host:
        return False
    text = absolute.lower()
    return any(keyword in text for keyword in ("contact", "about", "location", "visit", "find-us"))


def merge_socials(primary: Dict[str, str], fallback: Dict[str, str]) -> Dict[str, str]:
    merged = dict(primary)
    for label, value in fallback.items():
        if merged.get(label, "Not available") == "Not available" and value != "Not available":
            merged[label] = value
    return merged


def decode_ddg_link(url: str) -> str:
    if "duckduckgo.com/l/?" not in url:
        return url
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    uddg = params.get("uddg", [""])[0]
    return unquote(uddg) if uddg else url


def score_official_candidate(url: str, business_name: str) -> int:
    host = host_of(url)
    if not host:
        return -100
    score = 0
    if not is_directory_host(url):
        score += 5
    name_tokens = [token for token in re.findall(r"[a-z0-9]+", business_name.lower()) if len(token) > 2]
    for token in name_tokens[:4]:
        compact_host = host.replace("-", "").replace(".", "")
        if token in compact_host:
            score += 3
        if token in url.lower():
            score += 1
    if any(host.endswith(social) for social in ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com")):
        score -= 10
    return score


def search_public_pages(business_name: str, location_name: str) -> List[str]:
    query = f"{business_name} {location_name} official website"
    url = f"{DDG_HTML_URL}?q={quote_plus(query)}"
    html = safe_get(url, timeout=25)
    if not html:
        return []

    links, _ = parse_links(html)
    seen = set()
    candidates: List[Tuple[int, str]] = []
    for href, _ in links:
        resolved = decode_ddg_link(href)
        if not resolved.startswith(("http://", "https://")):
            continue
        host = host_of(resolved)
        if not host or host in seen:
            continue
        seen.add(host)
        candidates.append((score_official_candidate(resolved, business_name), resolved))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [url_value for score, url_value in candidates if score > -5][:4]


def extract_json_ld_address(html: str) -> str:
    for match in ADDRESS_JSON_RE.finditer(html or ""):
        raw = match.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        street = normalize_text(data.get("streetAddress", ""))
        city = normalize_text(data.get("addressLocality", ""))
        state = normalize_text(data.get("addressRegion", ""))
        postal = normalize_text(data.get("postalCode", ""))
        parts = [part for part in [street, city, state, postal] if part]
        if parts:
            return ", ".join(parts)
    return "Not available"


def enrich_from_site(business: Business, page_url: str, html: str) -> Business:
    links, meta = parse_links(html)
    title = extract_title(html)
    social_links = extract_social_links(links, page_url)
    linked_phones, linked_emails = extract_contact_links(links)

    phones = linked_phones or extract_phones(html)
    emails = linked_emails or extract_emails(html)
    address = extract_json_ld_address(html)

    if business.phone == "Not available" and phones:
        business.phone = phones[0]
    if business.email == "Not available" and emails:
        business.email = emails[0]
    if business.location == "Not available" and address != "Not available":
        business.location = address

    business.socials = merge_socials(business.socials, social_links)

    if business.website == "Not available" and not is_directory_host(page_url):
        business.website = page_url
    if page_url not in business.source_urls:
        business.source_urls.append(page_url)

    og_site_name = normalize_text(meta.get("og:site_name", ""))
    if business.website == "Not available" and (og_site_name or title):
        business.website = page_url

    website_host = host_of(page_url)
    for href, _ in links:
        if len(business.source_urls) >= 4:
            break
        if not likely_contact_page(href, page_url, website_host):
            continue
        contact_url = urljoin(page_url, href)
        if contact_url in business.source_urls:
            continue
        contact_html = safe_get(contact_url, timeout=20)
        if not contact_html:
            continue
        contact_links, _ = parse_links(contact_html)
        business.socials = merge_socials(
            business.socials, extract_social_links(contact_links, contact_url)
        )
        linked_contact_phones, linked_contact_emails = extract_contact_links(contact_links)
        if business.phone == "Not available":
            more_phones = linked_contact_phones or extract_phones(contact_html)
            if more_phones:
                business.phone = more_phones[0]
        if business.email == "Not available":
            more_emails = linked_contact_emails or extract_emails(contact_html)
            if more_emails:
                business.email = more_emails[0]
        if business.location == "Not available":
            more_address = extract_json_ld_address(contact_html)
            if more_address != "Not available":
                business.location = more_address
        business.source_urls.append(contact_url)

    return business


def enrich_business(business: Business, location_name: str, delay_seconds: float) -> Business:
    candidates: List[str] = []
    if business.website != "Not available":
        candidates.append(business.website)
    else:
        candidates.extend(search_public_pages(business.name, location_name))

    seen = set()
    for candidate in candidates:
        normalized = normalize_url(candidate)
        if normalized == "Not available" or normalized in seen:
            continue
        seen.add(normalized)
        html = safe_get(normalized, timeout=25)
        if not html:
            continue
        business = enrich_from_site(business, normalized, html)
        if delay_seconds:
            time.sleep(delay_seconds)
        if (
            business.website != "Not available"
            and business.phone != "Not available"
            and business.location != "Not available"
        ):
            break

    business.dedupe_key = make_dedupe_key(business.name, business.location)
    return business


def choose_best(
    businesses: Sequence[Business],
    limit: int,
    country_token: str,
    city_token: str,
    district_token: str,
    state_token: str,
) -> List[Business]:
    def is_location_match(location_value: str) -> bool:
        if location_value == "Not available":
            return False
        lowered = location_value.lower()
        city_ok = not city_token or city_token in lowered
        state_ok = not state_token or state_token in lowered or state_token[:2] in lowered
        return city_ok and state_ok

    def is_public_business(entry: Business) -> bool:
        host = host_of(entry.website) if entry.website != "Not available" else ""
        return not host.endswith(".gov") and not host.endswith(".mil")

    def score(entry: Business) -> int:
        value = 0
        if entry.location != "Not available":
            value += 3
        if entry.phone != "Not available":
            value += 2
        if entry.email != "Not available":
            value += 2
        if entry.website != "Not available":
            value += 3
        value += sum(1 for item in entry.socials.values() if item != "Not available")
        if is_location_match(entry.location):
            value += 4
        if country_token:
            value += 1
        if district_token and district_token in entry.location.lower():
            value += 2
        if entry.website != "Not available" and not is_directory_host(entry.website):
            value += 2
        return value

    ranked = sorted(businesses, key=lambda item: (-score(item), item.name.lower()))
    final: List[Business] = []
    seen = set()
    for business in ranked:
        if not is_public_business(business):
            continue
        if business.website == "Not available":
            continue
        if not is_location_match(business.location):
            continue
        if business.dedupe_key in seen:
            continue
        seen.add(business.dedupe_key)
        final.append(business)
        if len(final) >= limit:
            break
    return final


def collect_businesses(
    location: str = "",
    *,
    country: str = "",
    state: str = "",
    district: str = "",
    city: str = "",
    limit: int = 10,
    delay_seconds: float = 0.05,
) -> Tuple[LocationQuery, List[Business]]:
    location_parts = build_location_parts(
        location=location,
        country=country,
        state=state,
        district=district,
        city=city,
    )
    location_query = geocode_location(location_parts)
    discovered = overpass_businesses(location_query, limit=limit)
    discovered.sort(
        key=lambda item: (
            item.website == "Not available",
            item.location == "Not available",
            item.phone == "Not available",
            item.name.lower(),
        )
    )

    enriched: List[Business] = []
    for business in discovered:
        enriched.append(enrich_business(business, location_query.display_name, delay_seconds))
        if len(enriched) >= max(limit, 1):
            current = choose_best(
                enriched,
                limit=limit,
                country_token=location_query.country_token,
                city_token=location_query.city_token,
                district_token=location_query.district_token,
                state_token=location_query.state_token,
            )
            if len(current) >= limit:
                return location_query, current
        if len(enriched) >= max(limit * 2, limit):
            break

    final = choose_best(
        enriched,
        limit=limit,
        country_token=location_query.country_token,
        city_token=location_query.city_token,
        district_token=location_query.district_token,
        state_token=location_query.state_token,
    )
    return location_query, final


def format_business(entry: Business) -> str:
    lines = [
        f"Business Name: {entry.name}",
        f"Location: {entry.location}",
        f"Phone: {entry.phone}",
        f"Email: {entry.email}",
        f"Website: {entry.website}",
        "Social Media:",
        f"- Facebook: {entry.socials['Facebook']}",
        f"- Instagram: {entry.socials['Instagram']}",
        f"- LinkedIn: {entry.socials['LinkedIn']}",
        f"- X/Twitter: {entry.socials['X/Twitter']}",
        f"- YouTube: {entry.socials['YouTube']}",
        "----------------------------------------",
    ]
    return "\n".join(lines)


def write_output(path: str, businesses: Sequence[Business]) -> None:
    content = "\n".join(format_business(entry) for entry in businesses)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
