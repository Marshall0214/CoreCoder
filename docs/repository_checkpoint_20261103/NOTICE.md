# Evidence provenance and attribution

This folder preserves historical experiment records and selected verbatim excerpts.
`inputs.json` records SHA-256 values and original paths of the two reports and task manifest.
`cases/index.json` records the source path and SHA-256 of every exported context, patch and log.
These hashes establish consistency with the local records, not third-party certification.

Code and patch excerpts refer to the following upstream projects. Retained license notices
are in `licenses/`; repository/commit provenance and task metadata are in `inputs/manifest.json`.
The reports do not change the licenses of the embedded upstream material.

| Upstream | Retained notice |
| --- | --- |
| [pallets/click](https://github.com/pallets/click) | [LICENSE.txt](licenses/pallets-click-LICENSE.txt) |
| [pallets/itsdangerous](https://github.com/pallets/itsdangerous) | [LICENSE.rst](licenses/pallets-itsdangerous-LICENSE.rst) |
| [pytoolz/toolz](https://github.com/pytoolz/toolz) | [LICENSE.txt](licenses/pytoolz-toolz-LICENSE.txt) |
| [mahmoud/boltons](https://github.com/mahmoud/boltons) | [LICENSE](licenses/mahmoud-boltons-LICENSE) |
| [more-itertools/more-itertools](https://github.com/more-itertools/more-itertools) | [LICENSE](licenses/more-itertools-more-itertools-LICENSE) |

The repair workflow extends [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder)
by Yufeng He; see the repository [LICENSE](../../LICENSE) and source attribution in the README.
Model reasoning text and credentials are not included in the selected excerpts.

This packet supports offline report verification. It does not contain a complete locked
inference environment or all original temporary workspaces. New model execution and
fresh independent grading are separate activities and are not performed by `audit.py`.
