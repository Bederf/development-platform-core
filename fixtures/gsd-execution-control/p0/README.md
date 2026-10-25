# GSD Master 3.4.0 P0 test-only fixtures

These fixtures are deliberately non-authoritative. They exercise identity,
dependency, compatibility and authority-boundary checks for G0. They do not
represent controller state, a journal, a scheduler, an executor, or a release
artifact.

`controller-state-root/` is a logical fixture namespace only. It is distinct
from the legacy `.gsd-engine` namespace. Legacy run records are observations
from the host GSD skill and are never controller execution authority.
