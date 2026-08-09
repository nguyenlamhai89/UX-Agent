# UX Report Skills

These skills belong to the `ux-report` workflow and must run in this order:

1. [`visualize-insights`](visualize-insights/SKILL.md) generates the report and
   manifest.
2. After the user reviews and explicitly approves that report, [`send-email`](send-email/SKILL.md)
   asks for runtime recipients, prepares the complete draft, and sends only
   after a second explicit approval.

The workflow owns credential loading and the approval gates. The skills remain
responsible for deterministic report generation and Gmail SMTP delivery; the
email skill never reads `.env` directly.
