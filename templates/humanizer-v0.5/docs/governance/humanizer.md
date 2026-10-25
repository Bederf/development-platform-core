# Humanizer v0.5 Project Scaffold

Humanizer examines existing developer-written code in the project and uses it
as the local style reference for generated or AI-assisted changes. It reduces
AI-shaped complexity so new code follows the project's established patterns,
naming, structure, and level of abstraction. It is not intended to conceal
authorship or to optimize for the fewest lines.

The quality question is: would another developer recognize this as belonging
in the existing codebase and confidently maintain it? When reliable local
examples are unavailable, Humanizer must preserve the code or report that it
cannot establish a project-specific style reference. Transformations must
preserve behavior, security, validation, error handling, accessibility, public
interfaces, and required tests.

This project contains a dormant Humanizer scaffold. Presence does not grant
authority.

Lifecycle: `scaffolded → dormant → qualified → explicit activation → operational`. Installation never grants execution authority. Qualification never grants activation authority.

The scaffold is disabled until the project qualifies its semantic checker,
Forge executor, bounded/atomic write path, human verification process, and
conformance suite. Only the platform activation command may perform the
transition after it validates approved qualification evidence.

The platform template is a reference scaffold, not a shared executable
Humanizer service. The project owns and qualifies its implementation.
