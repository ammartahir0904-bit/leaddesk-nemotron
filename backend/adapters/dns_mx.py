"""Minimal stdlib DNS MX lookup through the system resolver (no extra dependency).

Answers whether a domain publishes mail-server (MX) records. That shows the
domain can receive email, not that a particular mailbox exists.
"""
import random
import re
import socket
import struct
import threading
from pathlib import Path

DOMAIN = re.compile(r'^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


def resolvers(path=Path('/etc/resolv.conf')):
    try:
        found = re.findall(r'^\s*nameserver\s+(\S+)', path.read_text(), re.M)
    except OSError:
        found = []
    return found[:2] or ['127.0.0.53']


def _query(domain):
    ident = random.randrange(65536)
    name = b''.join(bytes([len(part)]) + part.encode('ascii') for part in domain.split('.')) + b'\0'
    return ident, struct.pack('>HHHHHH', ident, 0x0100, 1, 0, 0, 0) + name + struct.pack('>HH', 15, 1)


def _skip_name(data, offset):
    while True:
        length = data[offset]
        if length & 0xC0 == 0xC0:
            return offset + 2
        if length == 0:
            return offset + 1
        offset += 1 + length


def parse(ident, data):
    """Returns 'has_mx', 'null_mx', 'no_mx' or 'no_domain'. Raises ValueError on malformed replies."""
    if len(data) < 12:
        raise ValueError('short reply')
    rid, flags, questions, answers = struct.unpack('>HHHH', data[:8])
    if rid != ident or not flags & 0x8000:
        raise ValueError('not our reply')
    rcode = flags & 0xF
    if rcode == 3:
        return 'no_domain'
    if rcode != 0:
        raise ValueError(f'rcode {rcode}')
    offset, found_null = 12, False
    for _ in range(questions):
        offset = _skip_name(data, offset) + 4
    for _ in range(answers):
        offset = _skip_name(data, offset)
        kind, _, _, length = struct.unpack('>HHIH', data[offset:offset + 10])
        if kind == 15:
            # RFC 7505 null MX: preference 0 and exchange "." means "accepts no mail".
            null = length == 3 and data[offset + 12] == 0
            if not null:
                return 'has_mx'
            found_null = True
        offset += 10 + length
    return 'null_mx' if found_null else 'no_mx'


def _read_name(data, offset, depth=0):
    labels = []
    while depth < 20:
        length = data[offset]
        if length & 0xC0 == 0xC0:
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            return '.'.join(labels + [_read_name(data, pointer, depth + 1)]).strip('.')
        if length == 0:
            return '.'.join(labels)
        labels.append(data[offset + 1:offset + 1 + length].decode('ascii', 'replace'))
        offset += 1 + length
        depth += 1
    raise ValueError('name too deep')


def parse_hosts(ident, data):
    """Mail-server host names ordered by preference; [] when there are none."""
    if len(data) < 12:
        raise ValueError('short reply')
    rid, flags, questions, answers = struct.unpack('>HHHH', data[:8])
    if rid != ident or not flags & 0x8000 or flags & 0xF not in {0, 3}:
        raise ValueError('bad reply')
    offset, hosts = 12, []
    for _ in range(questions):
        offset = _skip_name(data, offset) + 4
    for _ in range(answers):
        offset = _skip_name(data, offset)
        kind, _, _, length = struct.unpack('>HHIH', data[offset:offset + 10])
        if kind == 15:
            preference = struct.unpack('>H', data[offset + 10:offset + 12])[0]
            host = _read_name(data, offset + 12).casefold()
            if host and DOMAIN.fullmatch(host):
                hosts.append((preference, host))
        offset += 10 + length
    return [h for _, h in sorted(hosts)]


class MXLookup:
    def __init__(self, servers=None, timeout=2.0):
        self.servers, self.timeout = servers or resolvers(), timeout
        self.cache, self.lock = {}, threading.Lock()

    def __call__(self, domain):
        domain = domain.casefold().rstrip('.')
        if not DOMAIN.fullmatch(domain):
            return 'invalid'
        with self.lock:
            if domain in self.cache:
                return self.cache[domain]
        result = 'unknown'
        for server in self.servers:
            ident, packet = _query(domain)
            try:
                family = socket.AF_INET6 if ':' in server else socket.AF_INET
                with socket.socket(family, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(self.timeout)
                    sock.sendto(packet, (server, 53))
                    result = parse(ident, sock.recv(4096))
                    break
            except (OSError, ValueError, struct.error, IndexError):
                continue
        if result != 'unknown':
            with self.lock:
                self.cache[domain] = result
        return result

    def hosts(self, domain):
        """Preference-ordered MX host names for a valid domain; [] if none or unknown."""
        domain = domain.casefold().rstrip('.')
        if not DOMAIN.fullmatch(domain):
            return []
        for server in self.servers:
            ident, packet = _query(domain)
            try:
                family = socket.AF_INET6 if ':' in server else socket.AF_INET
                with socket.socket(family, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(self.timeout)
                    sock.sendto(packet, (server, 53))
                    return parse_hosts(ident, sock.recv(4096))[:3]
            except (OSError, ValueError, struct.error, IndexError):
                continue
        return []
