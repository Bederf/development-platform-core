# Development Platform Core + GSD Master

The projects are complementary, but they are not the same system.

| Concern | Development Platform Core | GSD Master |
| --- | --- | --- |
| Contracts and schemas | Owns | Consumes |
| Capability and authority boundaries | Owns | Applies during a phase |
| Evidence and acceptance model | Owns | Produces and routes evidence |
| Phase planning and execution waves | Provides contracts | Owns the lifecycle |
| Independent review and bounded correction | Defines compatible surfaces | Orchestrates the review cycle |
| Provider/model choice | Remains external | Routes through project bindings |

GSD Master is an independently released MIT-licensed developer skill. It is
installed and selected explicitly by a project; Core does not silently activate
it, install tooling, or change consumer authority.

The public package is available at
[`Bederf/gsd-master`](https://github.com/Bederf/gsd-master).

```text
project intent
    -> Core contract/specification validation
    -> GSD Master phase planning and execution waves
    -> bounded adapter/provider work
    -> evidence, review, and verification
    -> Core acceptance and governed closeout
```
