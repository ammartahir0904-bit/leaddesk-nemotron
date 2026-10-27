# Product requirements

## Personas and core outcome
Initial owner: Ammar, running a personal local-first tool. Later: individual freelancers or small teams. Primary outcome: fewer incorrect contacts and better-supported prospects, not maximum lead count.

## Required capabilities
| ID | Requirement | Acceptance behaviour |
|---|---|---|
| R01 | Arbitrary product/service input | Different industries work without code changes |
| R02 | Country/city/area targeting | Location evidence and business service area distinguished |
| R03 | Business discovery | Sources recorded; gaps and exhausted sources visible |
| R04 | Contact discovery | Phone, email, website and explicit WhatsApp links when available |
| R05 | Identity resolution | Company, branch, franchise and individual not silently merged |
| R06 | Need analysis | Evidence, alternative explanation and existing solution checked |
| R07 | Accurate terminology | Published, corroborated, direct-confirmed and unknown separated |
| R08 | Resource adaptation | Actual hardware detected and benchmarked |
| R09 | Voice assistant | Push-to-talk, transcription preview and cancel |
| R10 | Desktop context | User-authorised screen/window capture with visible indicator |
| R11 | File search | Search approved folders; show preview and open location |
| R12 | Memory | Save, inspect, correct, expire and delete memories |
| R13 | Learning panel | Corrections, datasets, evaluations, promotions and rollback |
| R14 | Integrations | Replaceable source, model, email and calendar adapters |
| R15 | Sales coordination | Approved replies, timezone-aware scheduling, duplicate protection |
| R16 | Reliability | Pause/resume, retries, audit trail, progress and backup |

## Input contract
Product description, business problem, capabilities, optional price/minimum deal size, target geography, service geography, exclusions, desired number of reviewed leads, freshness preference, allowed sources, depth/time budget. Ask only for essential ambiguities. Store generated targeting assumptions visibly and allow editing.

For a new offer the assistant generates buyer hypotheses and verification checks, then researches them. It must be able to change these hypotheses when evidence contradicts them.

## Priority output
The lead detail page shows business details, correct public contact routes and supported analysis together. Contact information is prominent but never detached from attribution and evidence. Unknown budget stays unknown. A price fit estimate must be labelled inference and never become a fact.

## Explicit non-goals for first release
Unrestricted desktop autonomy, phone-call negotiation, universal directory coverage, guaranteed buyer intent, autonomous contracting, continuous screen recording, foundation-model training, and immediate hosted multi-tenant SaaS.

## Lightweight and agile definition
Small independent modules, one deployment initially, bounded queues, optional models unloaded when idle, measurable slices, short feedback cycles, backwards-compatible contracts and migrations. 'Best' means better measured outcomes within resource limits, not most dependencies or most agents.
