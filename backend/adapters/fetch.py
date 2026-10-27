"""Bounded public HTTP fetches with DNS pinning, TLS verification and robots policy."""
import concurrent.futures
import http.client
import ipaddress
import socket
import ssl
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from backend.domain.errors import ResearchError

USER_AGENT = "LeadDesk/0.1"
MAX_BYTES = 3_000_000
TOTAL_SECONDS = 20
DNS_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="dns")


class CrossHostRedirect(ResearchError):
    """The page redirects to another host (brand.com -> brand.pk). The caller may read `location` instead, after its own checks."""

    def __init__(self, message, location):
        super().__init__(message, status=403)
        self.location = location


@dataclass
class Page:
    url: str
    body: bytes
    html: str


def validate_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username
                or parts.password or parts.port not in {None, 80, 443}
                or any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value):
            raise ValueError()
        hostname = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(hostname)
            if not address.is_global or address.is_multicast:
                raise ResearchError("Only public internet websites can be researched.", status=403)
        except ValueError:
            pass
        host = f"[{hostname}]" if ":" in hostname else hostname
        authority = host + (f":{parts.port}" if parts.port else "")
        # ASCII request target: avoid implicit platform-dependent URL handling.
        from urllib.parse import quote
        return urlunsplit((parts.scheme, authority, quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                           quote(parts.query, safe="%=&/?@!$'()*+,;:-._~"), ""))
    except (ValueError, UnicodeError):
        raise ResearchError("Enter a public http:// or https:// URL without credentials, using port 80 or 443.") from None


def public_addresses(host: str, port: int, timeout: float) -> list[str]:
    future = DNS_POOL.submit(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    try:
        addresses = list(dict.fromkeys(row[4][0] for row in future.result(timeout=timeout)))
    except (OSError, TimeoutError):
        future.cancel()
        raise ResearchError("The website could not be resolved. Check the address and retry.", retryable=True, status=502) from None
    if not addresses or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in addresses):
        raise ResearchError("The website resolves to a private or reserved address.", status=403)
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def request(url: str, deadline: float):
    url = validate_url(url)
    parts = urlsplit(url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ResearchError("Website request timed out. Retry when the website is available.", retryable=True, status=504)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = public_addresses(parts.hostname, port, min(remaining, 4))
    timeout = max(0.1, min(5, deadline - time.monotonic()))
    if parts.scheme == "https":
        conn = PinnedHTTPSConnection(parts.hostname, port, addresses[0], timeout)
    else:
        conn = http.client.HTTPConnection(addresses[0], port, timeout=timeout)
    try:
        target = urlunsplit(("", "", parts.path, parts.query, ""))
        conn.request("GET", target, headers={"Host": parts.netloc, "User-Agent": USER_AGENT,
                     "Accept": "text/html,text/plain;q=0.5", "Accept-Encoding": "gzip, identity", "Connection": "close"})
        response = conn.getresponse()
        headers = dict((key.lower(), value) for key, value in response.getheaders())
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, headers, b""
        encoding = headers.get("content-encoding", "identity").lower().strip()
        if encoding not in {"identity", "gzip", "x-gzip"}:
            raise ResearchError("This source requires unsupported content compression.")
        # gzip is inflated with a hard output bound, so a small compressed body cannot expand past the limit.
        inflate = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding != "identity" else None
        body = bytearray()
        while len(body) <= MAX_BYTES:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            chunk = response.read1(32768)
            if not chunk:
                break
            if inflate:
                try:
                    chunk = inflate.decompress(chunk, MAX_BYTES + 1 - len(body))
                except zlib.error:
                    raise ResearchError("The website sent a damaged compressed page.") from None
            body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise ResearchError("The page exceeds the 3 MB research limit. Try a smaller contact page.")
        return response.status, headers, bytes(body)
    except ssl.SSLCertVerificationError as error:
        # Certificate checks are never turned off: an invalid or incomplete certificate is reported as a finding.
        why = (error.verify_message or 'invalid certificate').rstrip('.')
        raise ResearchError(f"The website's security certificate could not be verified ({why}). Browsers may warn visitors too.",
                            status=502) from None
    except ssl.SSLError:
        raise ResearchError("The secure (HTTPS) connection to the website failed. Retry later.", retryable=True, status=502) from None
    except (TimeoutError, socket.timeout):
        raise ResearchError("Website request timed out. Retry when the website is available.", retryable=True, status=504) from None
    except (ConnectionError, http.client.HTTPException):
        raise ResearchError("The website dropped the connection. Retry later.", retryable=True, status=502) from None
    except OSError:
        raise ResearchError("The website could not be fetched securely. Check the URL and retry.", retryable=True, status=502) from None
    finally:
        conn.close()


def follow(url, deadline, *, origin=None, policy=None):
    for _ in range(4):
        if policy and not policy.can_fetch(USER_AGENT, url):
            raise ResearchError("The website's robots policy disallows this page.", status=403)
        status, headers, body = request(url, deadline)
        if status not in {301, 302, 303, 307, 308}:
            return url, status, headers, body
        if not headers.get("location"):
            break
        next_url = validate_url(urljoin(url, headers["location"]))
        if origin and urlsplit(next_url).netloc != origin:
            raise CrossHostRedirect("The page redirects to another host. Enter that website URL directly to research it.", next_url)
        if urlsplit(url).scheme == "https" and urlsplit(next_url).scheme != "https":
            raise ResearchError("The source redirects from HTTPS to an insecure connection.", status=403)
        url = next_url
    raise ResearchError("Too many redirects. Enter the website's final URL.")


def retry_delay(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if value.strip().isdigit() and len(value.strip()) <= 9:
            return float(value.strip())
        stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0, (stamp - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None


def fetch_page(value: str, *, budget_seconds: float = TOTAL_SECONDS) -> Page:
    url = validate_url(value)
    parts = urlsplit(url)
    if budget_seconds <= 0:
        raise ResearchError("The page time budget is exhausted.", status=429)
    deadline = time.monotonic() + min(TOTAL_SECONDS, budget_seconds)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    # RFC 9309: robots.txt redirects are followed even to another host (www.example.com -> example.com). Every hop is still
    # validated and pinned to a public address by request().
    _, status, robots_headers, body = follow(robots_url, deadline)
    policy = None
    if status in {401, 403}:
        raise ResearchError("This website restricts automated access.", status=403)
    if status != 404:
        if status != 200:
            raise ResearchError("The website's access policy is unavailable. Try again later.", retryable=True, status=502,
                                retry_after=retry_delay(robots_headers.get("retry-after")))
        policy = RobotFileParser()
        policy.parse(body.decode("utf-8", errors="replace").splitlines())
        if not policy.can_fetch(USER_AGENT, url):
            raise ResearchError("The website's robots policy disallows this page.", status=403)
    final_url, status, headers, body = follow(url, deadline, origin=parts.netloc, policy=policy)
    if status != 200:
        retryable = status == 429 or status >= 500
        raise ResearchError(f"The website returned HTTP {status}. Try another public page or retry later.",
                            retryable=retryable, status=502 if retryable else 422,
                            retry_after=retry_delay(headers.get("retry-after")) if retryable else None)
    content_type = headers.get("content-type", "").lower()
    if content_type.split(";")[0].strip() not in {"text/html", "application/xhtml+xml"}:
        raise ResearchError("This URL is not an HTML page. Enter a public website or contact page.")
    import re
    charset = re.search(r"charset=[\"']?([\w-]+)", content_type)
    try:
        html = body.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        html = body.decode("utf-8", errors="replace")
    return Page(final_url, body, html)
