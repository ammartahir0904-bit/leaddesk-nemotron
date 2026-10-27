"""Deterministic plain email and tentative personal calendar file serializers."""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime


def email_file(draft):
    document, context = draft['document'], draft['context']
    message = EmailMessage(policy=SMTP)
    message['From'] = document['sender']
    message['To'] = context['recipient']
    message['Subject'] = context['subject']
    message['Date'] = format_datetime(datetime.fromisoformat(draft['created_at']))
    message['Message-ID'] = f"<{draft['id']}@leaddesk.local>"
    message['X-Unsent'] = '1'
    message['X-LeadDesk-Source'] = 'synthetic' if draft['synthetic'] else 'source-reviewed'
    message.set_content(document['body'], charset='utf-8', cte='quoted-printable')
    return message.as_bytes()


def calendar_text(value):
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold_line(line):
    # RFC 5545: fold by UTF-8 octets without splitting a code point. The
    # continuation space also counts toward the next line's 75-octet limit.
    parts, current, size = [], '', 0
    for char in line:
        count = len(char.encode('utf-8'))
        if size + count > 75:
            parts.append(current)
            current, size = ' ', 1
        current += char
        size += count
    return '\r\n'.join([*parts, current])


def calendar_file(draft):
    document, context = draft['document'], draft['context']
    def utc(value):
        return datetime.fromisoformat(value).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    description = 'LeadDesk personal planning draft. Availability not checked; agreement not recorded; no invitation sent.'
    if draft['synthetic']:
        description = 'SYNTHETIC DEMO. ' + description
    description += '\n' + document['description']
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//LeadDesk//Local Planning Draft//EN',
             'CALSCALE:GREGORIAN', 'BEGIN:VEVENT', f"UID:{draft['id']}@leaddesk.local",
             f"SEQUENCE:{draft['revision'] - 1}", f"DTSTAMP:{utc(draft['updated_at'])}",
             f"DTSTART:{utc(context['start_utc'])}", f"DTEND:{utc(context['end_utc'])}",
             'STATUS:TENTATIVE', 'TRANSP:TRANSPARENT',
             'SUMMARY:' + calendar_text(context['title']), 'DESCRIPTION:' + calendar_text(description),
             'LOCATION:' + calendar_text(document['location']), 'END:VEVENT', 'END:VCALENDAR']
    return ('\r\n'.join(fold_line(line) for line in lines) + '\r\n').encode('utf-8')
