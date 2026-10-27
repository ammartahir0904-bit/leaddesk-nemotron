"""User-authored local files, never provider sending or booking instructions."""
import re
from datetime import datetime, timedelta, timezone
from email.headerregistry import Address
from email.errors import HeaderParseError
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DraftModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    @field_validator('*')
    @classmethod
    def no_controls(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError('Control characters are not supported.')
        return value


def mailbox(value):
    # One ASCII addr-spec. Display names, lists and international local parts
    # need a separately designed client/provider contract.
    if not value.isascii() or re.search(r'[\s<>(),;:\[\]\\"]', value):
        raise ValueError('Enter one plain ASCII email address, without a display name or list.')
    try:
        address = Address(addr_spec=value)
    except (ValueError, IndexError, HeaderParseError):
        raise ValueError('Enter one valid plain email address.') from None
    if (not address.username or len(address.username) > 64 or not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+', address.username)
            or address.username.startswith('.') or address.username.endswith('.') or '..' in address.username
            or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+', address.domain)):
        raise ValueError('Enter a plain email address with a DNS domain.')
    return value


class EmailDraft(DraftModel):
    kind: Literal['email']
    research_id: str = Field(min_length=1, max_length=100)
    contact_id: str = Field(min_length=1, max_length=100)
    sender: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=200, pattern=r'\S')
    body: str = Field(min_length=1, max_length=4000, pattern=r'\S')

    @field_validator('sender')
    @classmethod
    def plain_mailbox(cls, value):
        return mailbox(value)

    @field_validator('subject')
    @classmethod
    def one_line(cls, value):
        if '\n' in value or '\t' in value:
            raise ValueError('Email subjects must be one line.')
        return value


def resolve_meeting(document):
    try:
        zone, other = ZoneInfo(document.organizer_timezone), ZoneInfo(document.counterpart_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Choose valid IANA timezones installed on this computer.') from None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', document.start_local):
        raise ValueError('Enter a local date and time as YYYY-MM-DDTHH:MM.')
    wall = datetime.strptime(document.start_local, '%Y-%m-%dT%H:%M')
    if not 2000 <= wall.year <= 2100:
        raise ValueError('Calendar planning dates must be between 2000 and 2100.')
    candidates = {}
    for fold in (0, 1):
        utc = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == wall:
            candidates[fold] = utc
    if not candidates:
        raise ValueError('This local time does not exist because the timezone clock moves forward.')
    if len(set(candidates.values())) > 1 and document.fold is None:
        raise ValueError('This local time occurs twice. Choose the earlier or later occurrence explicitly.')
    start = candidates.get(document.fold if document.fold is not None else 0, next(iter(candidates.values())))
    end = start + timedelta(minutes=document.duration_minutes)
    return {'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
            'organizer_start': start.astimezone(zone).isoformat(), 'organizer_end': end.astimezone(zone).isoformat(),
            'counterpart_start': start.astimezone(other).isoformat(), 'counterpart_end': end.astimezone(other).isoformat(),
            'organizer_timezone': document.organizer_timezone, 'counterpart_timezone': document.counterpart_timezone,
            'availability': 'not_checked', 'agreement': 'not_recorded', 'invitation_sent': False}


class CalendarDraft(DraftModel):
    kind: Literal['calendar']
    title: str = Field(min_length=1, max_length=200, pattern=r'\S')
    description: str = Field(default='', max_length=4000)
    location: str = Field(default='', max_length=300)
    organizer_timezone: str = Field(min_length=1, max_length=80)
    counterpart_timezone: str = Field(min_length=1, max_length=80)
    start_local: str = Field(min_length=16, max_length=16)
    duration_minutes: int = Field(ge=5, le=480)
    fold: Literal[0, 1] | None = None
    synthetic: bool = False

    @field_validator('fold', mode='before')
    @classmethod
    def integer_fold(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError('Occurrence must be integer 0 or 1.')
        return value

    @model_validator(mode='after')
    def valid_meeting_time(self):
        resolve_meeting(self)
        return self


DraftInput = Annotated[EmailDraft | CalendarDraft, Field(discriminator='kind')]


class DraftEdit(DraftModel):
    expected_revision: int = Field(ge=1)
    document: DraftInput


class ExportReview(DraftModel):
    expected_revision: int = Field(ge=1)
    context_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewer: str = Field(min_length=1, max_length=80, pattern=r'\S')
    note: str = Field(min_length=1, max_length=400, pattern=r'\S')
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def literal_acknowledgement(cls, value):
        if value is not True:
            raise ValueError('Explicit review acknowledgement is required.')
        return value
