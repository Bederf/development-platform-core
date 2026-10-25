# Tool Boundary

Allowed tools are read-only repository and artifact readers:

- read files and directories;
- inspect version-control diff and status;
- inspect test definitions and returned test artifacts;
- inspect applicable contracts and architecture records;
- inspect static-analysis output.

Denied tools and actions:

- file creation, editing, deletion, or renaming;
- git add, commit, merge, push, reset, or checkout;
- database writes;
- deployment or service restart;
- external messages, approvals, or production actions.

The runtime or tool broker must enforce this boundary; prompt instructions are
not treated as an enforcement mechanism.
