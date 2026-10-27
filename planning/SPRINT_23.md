# Sprint 23: targeted search, websites read properly, layout, "what we offer" and a rules-first pitch

Dates: 26–27 October 2026, Asia/Karachi. Host: Intel i5-8265U, 7.5 GiB RAM, home broadband in Lahore. Local model: llama3.2:3b, digest `a80c4f17acd5…`. Chrome 151.0.7922.137.

## Why
The owner said that:
- contact and social searches did not find what they wanted, and web search found the wrong things;
- the AI text was generic;
- there was no place to enter a website;
- websites were not read properly;
- they wanted to see a site's layout and what we would offer that business.

## Delivered

### 1. Targeted search (`enrichment.py`, `search_context.py`)
- **Searches:** five per business. They use the lead's own city (from its address; a country-wide "UAE" search becomes the lead's city) and its type word, plus phone, Facebook and Instagram searches.
- **Context check:** a result must also mention the place, the business type or a valid local phone number. Otherwise it is listed as "possibly a different business" and gives no contacts.
- **Handles:** a social handle must match the name cleanly (`jci.sidi.mansour` is not Sidi Mansour). Words that are part of the business name do not count as context.
- **"Is this them? Yes / No"** applies immediately.
- **Social links from their own website** are merged.
- **Link-in-bio pages** (Linktree and similar) are read.
- **Page reads:** up to 5 result pages.

### 2. Contacts (`extract.py`)
- Cloudflare-protected emails are decoded.
- `name [at] domain [dot] com` is read as an email.
- `api.whatsapp.com/send?phone=` and "WhatsApp: 03xx…" are read as WhatsApp numbers.

### 3. Websites read properly
- **Fetching** (`fetch.py`):
  - 3 MB pages (was 1 MB);
  - gzip, with a hard output bound;
  - a page that forwards to another host is followed once and recorded;
  - robots.txt redirects are followed (RFC 9309).

  That last fix matters: www.indigoheights.com, www.sarteydevelopers.com and www.trustlinksrealty.com failed before it.
- **Extra pages:** up to 5 (reviews, gallery and team pages added).
- **Chrome reading (opt-in)** (`browser_render.py`):
  - uses the installed Chrome over its DevTools pipe; no download and no new Python package (Playwright was planned, but its wheel is 46 MB);
  - every request is checked, and private addresses are blocked;
  - a fresh temporary profile each time, and Chrome's own user agent;
  - screenshots are deleted after 24 hours.
- **Bot checks:** "Checking your browser" and CAPTCHA pages are detected and never used as the site; their screenshots are deleted.
- **"Coming soon" pages** are detected and counted as no working website.

### 4. Layout (`site_layout.py`)
- Menu, headings and sections.
- Call, WhatsApp, Book and Order buttons, including whether they show on the first phone screen.
- Sideways scrolling, tiny text, small buttons, broken images and PDF menus.
- Without Chrome, these are listed as "not measured", never guessed.

### 5. What we offer (`offer_fit.py`)
- A checklist of 19 features by business type, each Has / Missing / Not seen with evidence.
- The owner can untick what they do not deliver.

### 6. Pitch
- **Rules-first:** LeadDesk writes the fit, top gaps, a Keep/Fix/Add build plan, the opening message and the questions. Every sentence cites evidence.
- **AI** may only reword the message. The rewording is rejected if it adds facts, numbers, promises, earlier contact or field names.

### 7. Website boxes
- "Analyse a business website" in Find clients.
- "Add website" on each lead.

## Real checks (sample, not a benchmark)
| Site | Result |
|---|---|
| freddys.pk | Found online for Freddys Cafe (the old search had missed it). The source has 39 words; Chrome drew it as an "Opening Soon!" page. |
| salmandevelopers.com | Chrome was shown a "Checking your browser" page. Detected, screenshots deleted, and the source was read instead: 4 pages, email, phones and WhatsApp, grade A. |
| www.indigoheights.com | Previously failed (robots.txt redirect). Now read: 3 pages, 4 contacts. |
| skymarketing.com.pk, www.sarteydevelopers.com | Forwarding followed and recorded. Read in Chrome with phone and desktop screenshots. |
| Sidi Mansour (UAE) | Song pages and `jci.sidi.mansour` are no longer used. |

## Bugs found by live testing and fixed
- Chrome failed inside the server because `sh` cannot redirect file numbers above 9; it now uses `bash`.
- robots.txt redirects were refused.
- Buttons shown only on phones were missed.
- A website found online was counted as "no website".

## Not done
- `hydeparklahore.com` failed once with a generic error. It reads correctly now (certificate valid), so the failure was temporary. Fetch errors now name their cause (certificate, dropped connection, timeout).
