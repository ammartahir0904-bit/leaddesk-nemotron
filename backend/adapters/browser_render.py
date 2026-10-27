"""Optional page rendering with the Chrome already installed on this computer, for JavaScript websites and layout.

Talks to Chrome over its DevTools pipe (stdlib only, no download). Safety:
- the caller fetches the page with the normal reader first, so robots policy and HTTP errors are honoured before
  Chrome is used; a page that blocks automated readers is reported, never retried through Chrome;
- every request Chrome makes is paused and checked: only http(s) to public addresses is allowed, media is skipped,
  and at most MAX_REQUESTS are made;
- a fresh temporary profile per run (no cookies, logins or history), deleted afterwards; downloads are denied;
- Chrome's own user agent (HeadlessChrome) is sent unchanged; nothing pretends to be a person.
Screenshots are temporary: written under <data>/tmp/screens and deleted after SCREEN_TTL.
"""
import base64
import json
import os
import select
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from backend.domain.errors import ResearchError

CHROME_PATHS = ('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
PAGE_SECONDS = 20
SETTLE_SECONDS = 1.5   # at least this long after the load event
SETTLE_MAX = 8         # then until the visible text stops changing, at most this long (preloaders, sliders)
MAX_REQUESTS = 400
SCREEN_TTL = 24 * 3600
DESKTOP = {'width': 1366, 'height': 768, 'deviceScaleFactor': 1, 'mobile': False}
PHONE = {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True}
SKIP_TYPES = {'Media'}
BASH = shutil.which('bash') or '/bin/bash'

# Fixed, reviewed script: measures what a visitor sees. Never built from page content or model output.
LAYOUT_JS = r"""(() => {
  const vh = innerHeight, vw = innerWidth;
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  const txt = el => (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || el.value || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const top = el => Math.round(el.getBoundingClientRect().top + scrollY);
  const navLinks = [...document.querySelectorAll('nav a, header a, [role=navigation] a')].filter(vis);
  const nav = [...new Set(navLinks.map(txt).filter(t => t && t.length <= 40))].slice(0, 15);
  const headings = [...document.querySelectorAll('h1,h2,h3')].filter(vis).slice(0, 40)
    .map(h => ({ level: +h.tagName[1], text: txt(h), y: top(h) })).filter(h => h.text);
  const actions = [];
  for (const el of document.querySelectorAll('a,button,[role=button],input[type=submit]')) {
    if (actions.length >= 60) break;
    if (!vis(el)) continue;
    const href = (el.getAttribute('href') || '').toLowerCase(), t = txt(el), r = el.getBoundingClientRect();
    let kind = null;
    if (href.startsWith('tel:') || /\b(call( us| now)?|phone)\b/i.test(t)) kind = 'call';
    else if (/wa\.me|whatsapp/.test(href) || /whatsapp/i.test(t)) kind = 'whatsapp';
    else if (/\b(book|reserve|reservation|appointment|schedule)\b/i.test(t)) kind = 'book';
    else if (/\b(order|add to cart|cart|buy|shop now|checkout)\b/i.test(t)) kind = 'order';
    else if (href.startsWith('mailto:') || /\b(contact|enquir\w*|inquir\w*|get a quote|quote|message us|email us)\b/i.test(t)) kind = 'enquire';
    else if (/\bmenu\b/i.test(t) && !/\b(main menu|toggle|open menu|close)\b/i.test(t)) kind = 'menu';
    if (kind) actions.push({ kind, text: t || href.slice(0, 60), href: href.slice(0, 200), y: Math.round(r.top + scrollY),
      first_screen: r.top < vh && r.bottom > 0, w: Math.round(r.width), h: Math.round(r.height) });
  }
  const WORDS = { menu: /\bmenu\b|our food|dishes/, services: /\bservices?\b|what we do|treatments|solutions/, products: /\bproducts?\b|\bshop\b|collection/,
    gallery: /gallery|portfolio|photos|our work|projects/, reviews: /reviews?|testimonials?|what (our )?(clients|customers|patients) say|ratings/,
    pricing: /pricing|prices|packages|\bplans\b/, faq: /\bfaq\b|frequently asked/, team: /\bteam\b|our doctors|our staff|meet the|agents/,
    about: /about|our story|who we are/, contact: /contact|get in touch|find us|visit us/, listings: /listings|properties|for sale|for rent/,
    booking: /\bbook|appointment|reservation/, hours: /opening hours|timings|\bhours\b/ };
  const sections = {};
  let scanned = 0;
  for (const el of document.querySelectorAll('section, header, footer, article, main > div, [id]')) {
    if (scanned++ > 300) break;
    if (!vis(el)) continue;
    const head = el.querySelector('h1,h2,h3');
    const label = `${el.id} ${typeof el.className === 'string' ? el.className : ''} ${el.getAttribute('aria-label') || ''} ${head ? txt(head) : ''}`.toLowerCase();
    for (const [kind, re] of Object.entries(WORDS)) {
      if (!sections[kind] && re.test(label)) sections[kind] = { heading: head ? txt(head) : '', y: top(el) };
    }
  }
  if (document.querySelector('footer')) sections.footer = sections.footer || { heading: '', y: top(document.querySelector('footer')) };
  const iframes = [...document.querySelectorAll('iframe')].map(f => f.src).filter(Boolean).slice(0, 10);
  if (iframes.some(s => /google\.[a-z.]+\/maps|maps\.google|openstreetmap/.test(s))) sections.map = sections.map || { heading: 'Map', y: 0 };
  const h1 = [...document.querySelectorAll('h1')].find(vis);
  if (h1 && h1.getBoundingClientRect().top < vh) sections.hero = { heading: txt(h1), y: top(h1) };
  let tiny = 0, sampled = 0;
  for (const el of document.querySelectorAll('p,li,a,span,td,label')) {
    if (sampled >= 400) break;
    if (!el.childElementCount && (el.textContent || '').trim() && vis(el)) {
      sampled++;
      if (parseFloat(getComputedStyle(el).fontSize) < 12) tiny++;
    }
  }
  let small = 0, taps = 0;
  for (const el of document.querySelectorAll('a[href],button')) {
    if (taps >= 300) break;
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    taps++;
    if (r.height < 24 || r.width < 24) small++;
  }
  const sticky = [...document.querySelectorAll('header, nav, [class*=header]')].slice(0, 20)
    .some(el => ['fixed', 'sticky'].includes(getComputedStyle(el).position));
  const broken = [...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.src && !i.src.startsWith('data:')).length;
  const pdfs = [...document.querySelectorAll('a[href$=".pdf" i]')].filter(vis).map(a => ({ text: txt(a), href: a.getAttribute('href').slice(0, 200) })).slice(0, 10);
  return { nav, headings, actions, sections, iframes, pdf_links: pdfs, overflow: document.documentElement.scrollWidth > vw + 2,
    tiny_text: tiny, text_sampled: sampled, small_taps: small, taps_checked: taps, broken_images: broken, images: document.images.length,
    sticky_header: sticky, page_height: document.documentElement.scrollHeight,
    words: (document.body && document.body.innerText || '').split(/\s+/).filter(Boolean).length,
    title: document.title.slice(0, 200), viewport: { w: vw, h: vh } };
})()"""


def find_chrome():
    for path in [os.environ.get('LEADDESK_CHROME', '')] + list(CHROME_PATHS):
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which('google-chrome') or shutil.which('chromium') or None


@dataclass
class Rendered:
    url: str
    html: str
    layout: dict
    phone_layout: dict | None = None
    screens: dict = field(default_factory=dict)
    blocked: list = field(default_factory=list)
    requests: int = 0
    seconds: float = 0.0


class Pipe:
    """Chrome DevTools protocol over --remote-debugging-pipe: JSON messages separated by NUL bytes."""

    def __init__(self, chrome, profile):
        read_in, self.write_fd = os.pipe()
        self.read_fd, write_out = os.pipe()
        args = [chrome, '--headless=new', '--remote-debugging-pipe', f'--user-data-dir={profile}', '--no-first-run',
                '--no-default-browser-check', '--disable-extensions', '--disable-background-networking', '--disable-sync',
                '--disable-component-update', '--disable-default-apps', '--mute-audio', '--hide-scrollbars', 'about:blank']
        # Chrome reads commands on fd 3 and writes replies on fd 4. Its own messages go to a log in the temporary profile.
        self.log_path = os.path.join(profile, 'chrome.log')
        with open(self.log_path, 'wb') as log:
            # bash, not sh: dash cannot redirect file descriptors above 9, which a busy server process uses.
            self.proc = subprocess.Popen([BASH, '-c', 'exec "$@" 3<&"$CDP_IN" 4>&"$CDP_OUT"', 'bash', *args],
                                         pass_fds=(read_in, write_out), env={**os.environ, 'CDP_IN': str(read_in), 'CDP_OUT': str(write_out)},
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        os.close(read_in)
        os.close(write_out)
        self.buffer, self.next_id, self.events = b'', 0, []

    def send(self, method, params=None, session=None):
        self.next_id += 1
        message = {'id': self.next_id, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        os.write(self.write_fd, json.dumps(message).encode() + b'\0')
        return self.next_id

    def read(self, deadline):
        """One message, or None when the deadline passes."""
        while True:
            if b'\0' in self.buffer:
                raw, self.buffer = self.buffer.split(b'\0', 1)
                return json.loads(raw)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([self.read_fd], [], [], min(remaining, 0.5))
            if ready:
                chunk = os.read(self.read_fd, 1 << 20)
                if not chunk:
                    raise ResearchError('Chrome closed unexpectedly while reading the page.' + self.last_error(), retryable=True, status=502)
                self.buffer += chunk

    def last_error(self):
        try:
            with open(self.log_path, 'rb') as log:
                lines = [line for line in log.read()[-4000:].decode('utf-8', 'replace').splitlines() if line.strip()]
            return f' Chrome said: {lines[-1][:200]}' if lines else ''
        except OSError:
            return ''

    def close(self):
        try:
            self.send('Browser.close')
            self.proc.wait(5)
        except (OSError, subprocess.TimeoutExpired, ResearchError):
            self.proc.kill()
        for fd in (self.write_fd, self.read_fd):
            try:
                os.close(fd)
            except OSError:
                pass


class ChromeRenderer:
    def __init__(self, data_dir, check_host, chrome=None):
        """check_host(hostname, port) raises ResearchError for non-public addresses (fetch.public_addresses)."""
        self.data_dir, self.check_host = Path(data_dir), check_host
        self.chrome = chrome if chrome is not None else find_chrome()
        self.lock = threading.Lock()

    @property
    def screens_dir(self):
        return self.data_dir / 'tmp' / 'screens'

    def status(self):
        return {'installed': bool(self.chrome), 'path': self.chrome,
                'message': 'Google Chrome found on this computer.' if self.chrome else
                'Google Chrome or Chromium is not installed, so JavaScript websites are read without running their scripts.'}

    def expire_screens(self, now=None):
        now = now or time.time()
        if not self.screens_dir.exists():
            return
        for path in self.screens_dir.glob('*.jpg'):
            try:
                if now - path.stat().st_mtime > SCREEN_TTL:
                    path.unlink()
            except OSError:
                pass

    def screen_path(self, screen_id):
        try:
            uuid.UUID(screen_id[:36])
        except ValueError:
            return None
        if not screen_id.endswith(('-desktop', '-phone')):
            return None
        path = self.screens_dir / f'{screen_id}.jpg'
        if not path.exists() or time.time() - path.stat().st_mtime > SCREEN_TTL:
            return None
        return path

    def delete_screens(self, screen_ids):
        for screen_id in screen_ids:
            path = self.screen_path(screen_id)
            if path:
                path.unlink(missing_ok=True)

    def render(self, url, *, phone=True, screenshots=True):
        if not self.chrome:
            raise ResearchError('Chrome is not installed on this computer.', status=409)
        if not self.lock.acquire(timeout=60):
            raise ResearchError('Another page is being rendered. Retry shortly.', retryable=True, status=429)
        profile = tempfile.mkdtemp(prefix='leaddesk-chrome-')
        pipe = None
        started = time.monotonic()
        try:
            self.expire_screens()
            pipe = Pipe(self.chrome, profile)
            session = Session(pipe, self.check_host)
            session.open()
            desktop = session.load(url, DESKTOP)
            result = Rendered(url=desktop['url'], html=desktop['html'], layout=desktop['layout'])
            shot_id = str(uuid.uuid4())
            if screenshots:
                result.screens['desktop'] = self.save(f'{shot_id}-desktop', desktop['screenshot'])
            if phone:
                mobile = session.load(desktop['url'], PHONE)
                result.phone_layout = mobile['layout']
                if screenshots:
                    result.screens['phone'] = self.save(f'{shot_id}-phone', mobile['screenshot'])
            if result.screens:
                result.screens['expires_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + SCREEN_TTL))
            result.blocked, result.requests = session.blocked[:20], session.requests
            result.seconds = round(time.monotonic() - started, 2)
            return result
        finally:
            if pipe:
                pipe.close()
            shutil.rmtree(profile, ignore_errors=True)
            self.lock.release()

    def save(self, screen_id, data):
        if not data:
            return None
        self.screens_dir.mkdir(parents=True, exist_ok=True)
        (self.screens_dir / f'{screen_id}.jpg').write_bytes(data)
        return screen_id


class Session:
    def __init__(self, pipe, check_host):
        self.pipe, self.check_host = pipe, check_host
        self.session, self.blocked, self.requests, self.hosts = None, [], 0, {}

    def call(self, method, params=None, timeout=PAGE_SECONDS, session=True):
        message_id = self.pipe.send(method, params, self.session if session else None)
        deadline = time.monotonic() + timeout
        while True:
            message = self.pipe.read(deadline)
            if message is None:
                raise ResearchError(f'Chrome did not answer in time ({method}).', retryable=True, status=504)
            if message.get('id') == message_id:
                if 'error' in message:
                    raise ResearchError(f"Chrome could not {method}: {message['error'].get('message', '')[:200]}", status=502)
                return message.get('result') or {}
            self.handle(message)

    def wait(self, event, timeout):
        deadline = time.monotonic() + timeout
        while True:
            message = self.pipe.read(deadline)
            if message is None:
                return False
            if message.get('method') == event:
                return True
            self.handle(message)

    def idle(self, seconds):
        deadline = time.monotonic() + seconds
        while (message := self.pipe.read(deadline)) is not None:
            self.handle(message)

    def handle(self, message):
        if message.get('method') != 'Fetch.requestPaused':
            return
        params = message['params']
        request_id, url = params['requestId'], params['request']['url']
        reason = self.refuse(url, params.get('resourceType'))
        if reason:
            if len(self.blocked) < 50:
                self.blocked.append({'url': url[:200], 'reason': reason})
            self.pipe.send('Fetch.failRequest', {'requestId': request_id, 'errorReason': 'BlockedByClient'}, self.session)
        else:
            self.requests += 1
            self.pipe.send('Fetch.continueRequest', {'requestId': request_id}, self.session)

    def refuse(self, url, resource_type):
        parts = urlsplit(url)
        if parts.scheme not in {'http', 'https'}:
            return 'not a web address'
        if resource_type in SKIP_TYPES:
            return 'video or audio skipped'
        if self.requests >= MAX_REQUESTS:
            return 'request limit reached'
        host = (parts.hostname or '').casefold()
        if host not in self.hosts:
            try:
                self.check_host(host, parts.port or (443 if parts.scheme == 'https' else 80))
                self.hosts[host] = None
            except (ResearchError, OSError, ValueError) as error:
                self.hosts[host] = str(error)[:120] or 'not a public address'
        return self.hosts[host]

    def open(self):
        target = self.call('Target.createTarget', {'url': 'about:blank'}, session=False)['targetId']
        self.session = self.call('Target.attachToTarget', {'targetId': target, 'flatten': True}, session=False)['sessionId']
        self.call('Browser.setDownloadBehavior', {'behavior': 'deny'}, session=False)
        self.call('Page.enable')
        self.call('Fetch.enable', {'patterns': [{'urlPattern': '*', 'requestStage': 'Request'}]})

    def load(self, url, device):
        self.call('Emulation.setDeviceMetricsOverride', device)
        self.call('Emulation.setTouchEmulationEnabled', {'enabled': device['mobile']})
        navigation = self.call('Page.navigate', {'url': url})
        if navigation.get('errorText'):
            raise ResearchError(f"Chrome could not open the page ({navigation['errorText']}).", retryable=True, status=502)
        self.wait('Page.loadEventFired', PAGE_SECONDS)
        self.settle()
        final = self.evaluate('location.href') or url
        html = self.evaluate('document.documentElement.outerHTML') or ''
        layout = self.evaluate(LAYOUT_JS) or {}
        shot = self.call('Page.captureScreenshot', {'format': 'jpeg', 'quality': 60, 'captureBeyondViewport': False})
        return {'url': final, 'html': html[:3_000_000], 'layout': layout, 'screenshot': base64.b64decode(shot.get('data') or '')}

    def settle(self):
        """Let scripts draw the page: wait until the visible text length is stable for a second, within SETTLE_MAX."""
        started, last, stable = time.monotonic(), -1, 0
        self.idle(SETTLE_SECONDS)
        while time.monotonic() - started < SETTLE_MAX:
            size = self.evaluate('document.body ? document.body.innerText.length : 0') or 0
            stable = stable + 1 if size == last else 0
            if stable >= 2:
                return
            last = size
            self.idle(0.5)

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': False})
        if result.get('exceptionDetails'):
            return None
        return (result.get('result') or {}).get('value')
