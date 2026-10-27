# LeadDesk — engineering blueprint
Prepared for Ammar Tahir • 18 October 2026 • specification v0.1

Working name only; not a checked trademark. This package is a build specification, not a finished application or a report of measured performance.

## Product in one sentence
A lightweight personal assistant that researches suitable businesses for any product and location you specify, returns source-backed business/contact details and need analysis, and helps through voice, desktop context, file search, and correctable memory.

## Priority order
1. Correct business identity and contact attribution.
2. Useful, evidence-supported product fit and unmet-need analysis.
3. Low resource consumption and reliable completion.
4. Measurable improvement from corrections.
5. Outreach, meeting coordination, and richer automation.

A prospect does not have to advertise that it needs a developer. Discover latent needs through evidence. A weak website alone does not establish a need, and an inferred need is not confirmed purchase intent.

## Read in this order
- [Start tomorrow](START_HERE.md)
- [Requirements](docs/01_PRODUCT_REQUIREMENTS.md)
- [Architecture](docs/02_ARCHITECTURE.md)
- [Lead and contact engine](docs/03_LEAD_ENGINE.md)
- [Desktop assistant](docs/04_DESKTOP_ASSISTANT.md)
- [Hardware and models](docs/05_HARDWARE_MODELS.md)
- [Feedback and learning](docs/06_FEEDBACK_LEARNING.md)
- [Data and API contracts](docs/07_DATA_API.md)
- [Panels and user flows](docs/08_PANELS.md)
- [Integrations and sales](docs/09_INTEGRATIONS.md)
- [Quality and evaluation](docs/10_QUALITY.md)
- [Delivery backlog](docs/11_BACKLOG.md)
- [Operations and privacy](docs/12_OPERATIONS.md)
- [Decisions, risks, sources](docs/13_DECISIONS_SOURCES.md)
- [Agent implementation instructions](AGENTS.md)
- [Reusable task brief](templates/BUILD_TASK.md)

## Known environment
Laptop: Ubuntu, 8 GB RAM, 8 GB swap. GPU wording was ambiguous; default to CPU-only until detected. A stronger PC may be available, but its CPU, RAM, GPU and VRAM are unknown. Swap is emergency capacity, not additional fast RAM. Do not infer the user's real machine specifications from a cloud development container.

## Delivery boundaries
Includes architecture, interfaces, proposed thresholds, acceptance tests, and an ordered implementation backlog. Does not include executable product code, live leads, trained weights, API credentials, or guaranteed sales. All performance budgets and quality thresholds below are proposed acceptance targets to test, not achieved results. No specific model is declared best before benchmarking.
