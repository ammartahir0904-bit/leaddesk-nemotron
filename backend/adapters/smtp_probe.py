"""Ask a domain's own mail server whether a mailbox exists, without sending any email.

The conversation stops after RCPT TO: no DATA command is ever sent, so no message
is delivered. A second RCPT to a random address detects "catch-all" domains that
accept every address (then the answer proves nothing). Only the MX hosts that DNS
publishes for that domain are contacted, on port 25. Results are cached per
address for a day and probes are spaced per domain. Called only on explicit request.

Limits: some servers accept everything, greylist (try later) or block home IPs;
those come back as catch_all / unknown / blocked, never as "verified".
"""
import secrets
import smtplib
import socket
import threading
import time
from datetime import datetime, timezone

TIMEOUT = 10
CONNECT_TIMEOUT = 5
SPACING = 2.0  # seconds between probes to the same domain


def classify(code, message):
    text = message.decode('utf-8', 'replace') if isinstance(message, bytes) else str(message)
    lower = text.casefold()
    if code in {250, 251}:
        return 'accepted'
    if code in {550, 551, 553} and any(k in lower for k in ('does not exist', 'no such', 'unknown', 'not found', 'invalid',
                                                            'user unknown', 'mailbox unavailable', 'recipient rejected',
                                                            'no mailbox', 'not exist', '5.1.1', '5.1.0')):
        return 'rejected'
    if code in {552} and 'full' in lower:
        return 'full'
    if any(k in lower for k in ('spamhaus', 'blocked', 'blacklist', 'blocklist', 'block list', 'reputation', 'not allowed', 'policy')):
        return 'blocked'
    if 400 <= code < 500:
        return 'unknown'  # greylisting or temporary failure: try again later
    return 'rejected' if code in {550, 551, 553} else 'unknown'


class SMTPProbe:
    def __init__(self, mx_hosts, connect=None, helo='leaddesk.localhost', clock=time.monotonic):
        self.mx_hosts, self.helo, self.clock = mx_hosts, helo, clock
        self.connect = connect or self._connect
        self.cache, self.last, self.lock = {}, {}, threading.Lock()
        self.blocked_families = set()  # e.g. home ISPs often block outgoing port 25 over IPv4 only

    def _connect(self, host):
        """IPv6 first, at most two addresses, short timeouts; a family whose port 25 times out is skipped afterwards."""
        addresses = sorted(dict.fromkeys((info[0], info[4][0]) for info in socket.getaddrinfo(host, 25, 0, socket.SOCK_STREAM)),
                           key=lambda a: a[0] != socket.AF_INET6)
        usable = [a for a in addresses if a[0] not in self.blocked_families]
        if not usable:
            raise OSError('port 25 is blocked on this network for ' + ('IPv4' if addresses and addresses[0][0] == socket.AF_INET else 'this address type'))
        error = None
        for family, address in usable[:2]:
            if family in self.blocked_families:
                continue
            server = smtplib.SMTP(timeout=CONNECT_TIMEOUT, local_hostname=self.helo)
            try:
                server.connect(address, 25)
                server.timeout = TIMEOUT
                server.sock.settimeout(TIMEOUT)
                return server
            except socket.timeout as failure:
                self.blocked_families.add(family)
                error = failure
            except OSError as failure:
                error = failure
        raise error

    def check(self, address):
        address = address.strip()
        local, _, domain = address.rpartition('@')
        domain = domain.casefold()
        key = address.casefold()
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self.lock:
            cached = self.cache.get(key)
            if cached and self.clock() - cached[0] < 86400:
                return cached[1]
        hosts = self.mx_hosts(domain)
        if not local or not hosts:
            result = {'result': 'no_mail_server', 'detail': 'The domain publishes no mail server, so email cannot be delivered.',
                      'server': None, 'checked_at': now}
            return self._keep(key, result)
        with self.lock:
            wait = SPACING - (self.clock() - self.last.get(domain, -SPACING))
        if wait > 0:
            time.sleep(wait)
        result = None
        for host in hosts[:2]:
            try:
                server = self.connect(host)
            except (OSError, smtplib.SMTPException) as error:
                blocked_v4 = socket.AF_INET in self.blocked_families
                result = {'result': 'unreachable', 'detail': f'Could not connect to {host} on port 25 ({type(error).__name__}). ' +
                          ('Your internet connection blocks outgoing port 25 over IPv4, so this mail server cannot be asked.'
                           if blocked_v4 else 'Your network may block outgoing port 25.'), 'server': host, 'checked_at': now}
                continue
            try:
                server.ehlo_or_helo_if_needed()
                code, message = server.mail('')
                if code >= 400:
                    result = {'result': classify(code, message), 'detail': f'Sender refused: {code}', 'server': host, 'checked_at': now}
                    break
                code, message = server.rcpt(address)
                verdict = classify(code, message)
                if verdict == 'accepted':
                    probe_code, _ = server.rcpt(f'leaddesk-{secrets.token_hex(6)}@{domain}')
                    if probe_code in {250, 251}:
                        verdict = 'catch_all'
                text = (message.decode('utf-8', 'replace') if isinstance(message, bytes) else str(message))[:200]
                result = {'result': verdict, 'detail': f'{code} {text}'.strip(), 'server': host, 'checked_at': now}
                break
            except (OSError, smtplib.SMTPException, socket.timeout) as error:
                result = {'result': 'unknown', 'detail': f'The mail server ended the check early ({type(error).__name__}).',
                          'server': host, 'checked_at': now}
            finally:
                try:
                    server.rset()
                    server.quit()
                except (OSError, smtplib.SMTPException):
                    pass
        with self.lock:
            self.last[domain] = self.clock()
        return self._keep(key, result)

    def _keep(self, key, result):
        with self.lock:
            self.cache[key] = (self.clock(), result)
        return result
