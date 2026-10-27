# Sprint 24: contact review gate, corrections that change results, learned rules, quality report

Date: 27 October 2026, Asia/Karachi. Host: Intel i5-8265U, 7.5 GiB RAM. Model: llama3.2:3b, digest `a80c4f17acd5…`.

## Why
The owner said several things were still being ignored:
- contacts were not trustworthy (wrong, fake or temporary emails and numbers shown as good);
- Instagram and Facebook were missing;
- AI output was weak;
- 👍/👎 did nothing.

The last point was true: the verdict was saved and never read.

## Delivered

### Contact review gate (`contact_review.py`, `contact_review_v1`)
Every phone and email is **approved**, **needs review** or **rejected**, with every reason listed.

**Rejected:**
- temporary-email domains (local list: 9,963 domains, CC0, retrieved 2026-10-27, SHA-256 recorded; refreshed by `scripts/update_disposable_domains.py`);
- placeholder addresses (`test@`, `name@domain.com`) and image file names (`logo@2x.png`);
- no-reply addresses, and website-platform domains (wix, sentry and similar);
- domains that do not exist or take no email (from saved MX answers);
- mailboxes rejected by their mail server;
- numbers invalid for the numbering plan, 0000000 or straight runs (1234567), and reserved example numbers;
- the same contact on 3+ unrelated businesses (branches of one brand excepted);
- anything the owner marked wrong, or that an approved rule blocks.

**Needs review:**
- one source only;
- catch-all or blocked mailbox checks;
- an email domain that is not their website;
- premium, toll-free or shared-cost numbers;
- 7 identical digits, which may be a vanity number.

**Approved:** valid, no warning, and shown on their own website, found in two independent sources, or accepted by their mail server.

Rejected contacts are hidden from lists, filters, scores, messages, WhatsApp links and the CSV. They are shown in "Rejected contacts", with an override. The CSV includes approved contacts only, unless "Include contacts that need review" is ticked. The mailbox check is on by default in the review, with an off switch.

### Corrections that change results (migration 018)
- **Contacts:** Wrong (not theirs / disconnected / fake / temporary), "This is correct", or "Add a contact you know".
  - Keyed to the business, so they apply in every future search of it.
  - "Fake" and "temporary" block the value everywhere; "temporary" also blocks the domain.
  - Undo works, including after the reason was changed.
- **Feature corrections:** "Actually they have it / they don't" replaces detection, shows what LeadDesk had found, and rebuilds the pitch at once.
- **"Is this them?" answers** now apply to the business across searches.
- **Messages:** Approve / Edit (your text is used, including in the CSV) / Reject with a reason. These replace 👍/👎.
- **Message templates** now exist for every feature, so a remaining gap always gives a specific message.

### Learned rules (`rule_proposals.py`)
- A rule is proposed only after 3 or more corrections of the same kind: block an email domain, distrust a source host, or switch off a detector for a business type.
- Each proposal shows the corrections it came from and how many current results it would change.
- A rule is active only after approval, and can be switched off. No model weights change.

### Quality report (`lead_quality.py`)
- Approved / needs review / rejected and owner-corrected, per source.
- Top rejection reasons and checks the owner corrected.
- Message outcomes and the AI-rewording acceptance rate.
- Week by week, with every rate shown with its counts and dates. Downloadable as CSV.

### Search engines
- Bing and Qwant enabled in `deploy/searxng/settings.yml` (Startpage and Mojeek did not become active in this SearXNG version).
- Each search records results per engine and which engines were blocking.
- If every engine refuses, **nothing is saved** and the owner is told to retry, instead of a false "nothing found". Partial blocking marks the result incomplete.
- Answers are cached for 6 hours so retries do not repeat queries.
- When no Instagram or Facebook page is found, extra searches run: without the city, and by likely handle.

### Other
- Fetch errors name their cause: an invalid certificate (reported as a finding; certificate checking is never turned off), a dropped connection or a timeout.
- Old saved searches no longer list Facebook posts as "possibly a different business".

## Tests
`unittest discover` passes 430+ tests, including:
- `tests/test_contact_review.py`: every rule, mailbox answers, shared contacts vs branches, corrections across searches, undo, rules, report;
- engine blocking and fallback searches;
- named fetch failures.

## Real results (this laptop, 27 October 2026)
**Contact review on all saved searches** (753 contacts, 7 searches, 2026-10-24 to 2026-10-26):
- **9 approved, 722 need review, 22 rejected.**
- Most need review because they come from a single map source.
- Spot check with live DNS: 4 rejected domains have no name servers, and the 5th has no mail server, as the review said.

**Live correction run:**
- Marking a Cafe Costa number "not theirs" hid it from the list at once. It was a Costa Coffee Pakistan number from an older search.
- A feature correction on Salman Developers rebuilt the message around the remaining gap (no enquiry form).
- Both corrections were undone afterwards.

**Social discovery** (same 18 saved leads, searches only):
- Before the changes: **8/18** with a confirmed Instagram or Facebook (engines answering: Google CSE 369 results, Brave 31; DuckDuckGo none).
- The "after" run is **not valid**. My two back-to-back runs (about 150 queries) made every engine block automated searches: Brave and Google CSE said too many requests, Qwant access denied, DuckDuckGo a CAPTCHA.
- No improvement is claimed. Re-measure when the engines answer again, at a slower pace.

**Audit sheet:** `.local/audit/sprint-24-contact-audit.csv` holds 30 contacts (9 approved, 10 rejected, 11 needs review) for the owner to mark. Precision is reported only after those marks.

## Not done
- **Model comparison** (llama3.2:3b vs a larger free model on the same 20 leads): needs the owner's yes to download a model.
- **Rate limits:** free search engines limit automated searches. Large batches (top 10 × 4–8 searches) can hit those limits; the app now says so instead of hiding it.
