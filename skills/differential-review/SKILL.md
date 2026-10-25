---
name: differential-review
description: Perform evidence-based security and regression review of commits, diffs, and pull-request changes.
---

# Differential review

Review changed behavior against the parent baseline. Triage by risk rather than
diff size, inspect relevant history, identify affected callers and trust
boundaries, and check test coverage. Findings must cite files and lines,
describe a concrete impact, and state confidence and coverage limits. Treat
removed validation or authorization as high-risk until disproved. Produce a
review artifact when the surrounding workflow expects one.
