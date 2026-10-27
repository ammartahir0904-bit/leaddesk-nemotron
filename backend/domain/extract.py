"""Conservative, deterministic extraction. Source presence is not ownership."""
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit
from backend.domain.errors import ResearchError

EMAIL = re.compile(r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Z0-9](?:[A-Z0-9.-]{0,251}[A-Z0-9])?\.[A-Z]{2,63}(?![\w.-])", re.I)
PHONE = re.compile(r"(?<!\w)(?:\+\d[\d ()-]{6,24}\d|\(?\d{2,4}\)?[ -]\d[\d ()-]{4,20}\d)(?!\w)")
# "name [at] domain [dot] com" and similar: only bracketed forms, so ordinary sentences with "at" are not read as emails.
OBFUSCATED = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]{1,64})\s*[\[({]\s*at\s*[\])}]\s*([A-Z0-9-]{1,63}(?:\s*(?:[\[({]\s*dot\s*[\])}]|\.)\s*[A-Z0-9-]{1,63}){1,4})(?![\w-])", re.I)
DOT = re.compile(r"\s*(?:[\[({]\s*dot\s*[\])}]|\.)\s*", re.I)
WHATSAPP_TEXT = re.compile(r"whats\s?app\b[^0-9+]{0,20}(" + r"(?:\+\d[\d ()-]{6,24}\d|\(?\d{2,4}\)?[ -]?\d[\d ()-]{4,20}\d)" + r")", re.I)
CFEMAIL_ELEMENT = re.compile(r"<(?P<tag>[a-z][a-z0-9]*)\b[^>]*\bdata-cfemail=[\"']?(?P<hex>[0-9a-f]{4,600})[\"']?[^>]*>.*?</(?P=tag)>", re.I | re.S)
CFEMAIL_LINK = re.compile(r"(href=[\"']?)/cdn-cgi/l/email-protection#(?P<hex>[0-9a-f]{4,600})", re.I)
MAX_HTML = 3_000_000
SKIP = {"script", "style", "noscript", "template", "svg", "head"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK = {"p", "div", "section", "article", "header", "footer", "li", "h1", "h2", "address", "br", "tr"}


class VisiblePage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.lines = []
        self.buffer = []
        self.heading = []
        self.heading_count = 0
        self.links = []
        self.active_links = []
        self.events = 0

    def budget(self):
        self.events += 1
        if self.events > 150000 or len(self.stack) > 128:
            raise ResearchError("This HTML page is too complex to inspect within the research limit. Try a smaller public contact page.")

    def flush(self):
        value = " ".join("".join(self.buffer).split())
        if value:
            self.lines.append(value)
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        self.budget()
        attrs = dict(attrs)
        style = re.sub(r"\s", "", attrs.get("style", "")).lower()
        hidden = (any(s[1] for s in self.stack) or tag in SKIP or "hidden" in attrs
                  or attrs.get("aria-hidden") == "true" or "display:none" in style or "visibility:hidden" in style)
        if tag in BLOCK:
            self.flush()
        if tag not in VOID:
            self.stack.append((tag, hidden))
        if tag == "h1" and not hidden:
            self.heading_count += 1
        if tag == "a" and not hidden:
            self.active_links.append({"href": attrs.get("href", ""), "parts": []})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        self.budget()
        if tag == "a" and self.active_links:
            link = self.active_links.pop()
            label = " ".join("".join(link["parts"]).split())
            if label:
                self.links.append((link["href"], label))
        if tag in BLOCK:
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.budget()
        if any(s[1] for s in self.stack):
            return
        self.buffer.append(data)
        if self.heading_count == 1 and any(tag == "h1" for tag, _ in self.stack):
            self.heading.append(data)
        for link in self.active_links:
            link["parts"].append(data)


def cf_decode(hexed):
    """Cloudflare email protection: the first byte is an XOR key for the rest. Browsers show the decoded address."""
    try:
        data = bytes.fromhex(hexed)
        return "".join(chr(b ^ data[0]) for b in data[1:])
    except (ValueError, IndexError):
        return ""


def reveal_protected_emails(html):
    """Replace Cloudflare-protected addresses with the text a visitor's browser shows; links become mailto: links."""
    if "cdn-cgi/l/email-protection" not in html and "data-cfemail" not in html:
        return html
    def element(match):
        value = cf_decode(match.group("hex"))
        return value if EMAIL.fullmatch(value) else match.group(0)
    def link(match):
        value = cf_decode(match.group("hex"))
        return match.group(1) + "mailto:" + value if EMAIL.fullmatch(value) else match.group(0)
    return CFEMAIL_LINK.sub(link, CFEMAIL_ELEMENT.sub(element, html))


def whatsapp_number(url):
    """The number in a WhatsApp chat link: wa.me/923001234567, api.whatsapp.com/send?phone=…, whatsapp://send?phone=…"""
    host = (url.hostname or "").casefold()
    if url.scheme == "https" and host == "wa.me":
        value = url.path.strip("/")
    elif (url.scheme in {"https", "http"} and host in {"api.whatsapp.com", "web.whatsapp.com", "whatsapp.com", "www.whatsapp.com"}
          and url.path.rstrip("/") in {"/send", ""}) or (url.scheme == "whatsapp" and host == "send"):
        value = (parse_qs(url.query).get("phone") or [""])[0]
    else:
        return None
    value = re.sub(r"[\s+()-]", "", unquote(value))
    return "+" + value if re.fullmatch(r"[1-9]\d{6,14}", value) else None


@dataclass
class Extracted:
    name: str | None
    name_excerpt: str | None
    contacts: list[dict] = field(default_factory=list)
    source_excerpts: list[str] = field(default_factory=list)


def extract(html: str) -> Extracted:
    if len(html) > MAX_HTML:
        raise ResearchError("The page exceeds the extraction size limit. Try a smaller public contact page.")
    html = reveal_protected_emails(html)
    parser = VisiblePage()
    parser.feed(html)
    parser.flush()
    heading = (" ".join(" ".join(parser.heading).split())[:300] or None) if parser.heading_count == 1 else None
    result = Extracted(heading, heading)
    seen = set()

    def add(kind, raw, excerpt, normalized=None):
        normalized = normalized or raw
        key = (kind, normalized)
        if key in seen or len(result.contacts) >= 50:
            return
        seen.add(key)
        # Keep the exact supporting characters and a bounded context around them.
        position = excerpt.find(raw)
        start = max(0, position - 100)
        result.contacts.append({"type": kind, "raw_value": raw,
                                "normalised_value": normalized, "excerpt": excerpt[start:start + 400]})

    for line in parser.lines:
        for match in EMAIL.finditer(line):
            value = match.group()
            if len(value) > 254:
                continue
            local, domain = value.rsplit("@", 1)
            add("email", value, line, f"{local}@{domain.lower()}")
        for match in OBFUSCATED.finditer(line):
            value = f"{match.group(1)}@{DOT.sub('.', match.group(2))}"
            if len(value) <= 254 and EMAIL.fullmatch(value):
                local, domain = value.rsplit("@", 1)
                # The excerpt keeps the written form ("info [at] cafe [dot] pk"); the value is the address it spells.
                add("email", value, line[max(0, match.start() - 100):], f"{local}@{domain.lower()}")
        for match in WHATSAPP_TEXT.finditer(line):
            value = match.group(1).strip()
            digits = re.sub(r"\D", "", value)
            if 7 <= len(digits) <= 15:
                add("whatsapp", value, line, "+" + digits if value.startswith("+") else None)
        for match in PHONE.finditer(line):
            value = match.group().strip()
            digits = re.sub(r"\D", "", value)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or re.fullmatch(r"\d{2}-\d{2}-\d{4}", value):
                continue
            if 7 <= len(digits) <= 15:
                # No inferred country code for local numbers.
                add("phone", value, line, "+" + digits if value.startswith("+") else None)
    for href, label in parser.links:
        try:
            url = urlsplit(href)
        except ValueError:
            continue
        number = whatsapp_number(url)
        if number:
            add("whatsapp", number, f"{label} — link: {href}", number)
        # A hidden mailto/tel value does not count as visible source text.
        elif url.scheme == "mailto":
            value = unquote(url.path)
            if len(value) <= 254 and EMAIL.fullmatch(value) and value in label:
                local, domain = value.rsplit("@", 1)
                add("email", value, label, f"{local}@{domain.lower()}")
    # A small visible-text context bank supports later manual analysis without
    # retaining whole page bodies. These are source quotes, never inferred facts.
    existing = {result.name, *(contact["excerpt"] for contact in result.contacts)}
    for line in parser.lines:
        excerpt = line[:400]
        if len(excerpt) >= 10 and excerpt not in existing:
            result.source_excerpts.append(excerpt)
            existing.add(excerpt)
        if len(result.source_excerpts) >= 12:
            break
    return result
