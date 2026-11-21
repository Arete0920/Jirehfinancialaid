# Jireh Financial Aid

This repository is a separate working copy of the CROWN CSMS source baseline
for developing the Jireh Financial Aid solution. It preserves shared application
code and existing Jireh work so development can continue without rebuilding
from scratch. The source repository is unchanged.

## Starting point

The initial source baseline was copied from
[`Arete0920/Crown-CSMS`](https://github.com/Arete0920/Crown-CSMS) at commit
`ac9fab0981c281f9815b20160d37da4fa8e5bd1f` (2026-11-21). This is intentionally
a broad baseline, not a completed extraction: Jireh's application workflows
currently depend on CROWN's shared identity, authorization, tenant, aid, and
financial services. Other CROWN modules remain in this repository until those
dependencies can be separated and validated safely.

The source migration omitted GitHub Actions workflows and agent instructions,
as well as a checked-in private key. No credentials, local databases, or
deployment workflow were copied.

## Development

Start with the [engineering setup guide](docs/engineering/DEV_SETUP.md) for
the supported toolchain, backend and frontend commands, and local development
instructions. For the Jireh product boundaries and current capabilities, see
the [Jireh website migration guide](docs/operations/JIREH_FAMILY_WEBSITE_MIGRATION_20261015.md)
and [Jireh site README](sites/jireh/README.md).

## Hosting and release status

Azure credentials, connections, resources, and deployment workflows have not
been configured for this repository. No deployment, DNS change, live financial
processing, or production access is authorized by this source copy. Treat any
future infrastructure setup or release as a separate, explicitly reviewed
change.

Source availability and automated checks do not establish that a feature or
hosted environment is ready for release. See [SECURITY.md](SECURITY.md) for
security reporting information and the repository's inherited [NOTICE.md](NOTICE.md)
for ownership and rights information.
