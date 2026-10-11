# Review dates and repository health

The catalog records two different kinds of evidence:

- **Documentation reviewed:** `last_reviewed` in a project record. A human read
  the cited upstream sources on that date. It is not a runtime test.
- **Repository checked:** a dated observation of public GitHub repository metadata
  in [`data/health.json`](../data/health.json). It does not update the human review date.

Last observed push is GitHub's repository-level `pushed_at`, not the date of a
release or necessarily a code change on the default branch. Recent activity does
not establish maintenance, security, quality, or compatibility. Inactivity does
not establish abandonment. Archived and disabled are GitHub flags, not catalog
inclusion decisions.

## Snapshot format

The snapshot is an object keyed by catalog project ID. Each observation has these
fields; unknown or misspelled fields fail validation.

| Field | Meaning |
| --- | --- |
| `repository` | The catalog URL that was requested. Observations for a different URL or removed ID are not used. |
| `checked_at` | Latest check-attempt date, `YYYY-MM-DD` in UTC. |
| `status` | `reachable`, `unavailable`, or `check-failed`; defined below. |
| `detail` | A short failure explanation, or `null` after success. |
| `last_successful_check` | Date the retained public metadata was fetched successfully, or `null` if never observed. |
| `canonical_repository` | GitHub's reported repository URL, or `null` before a successful check. A changed URL flags a redirect for review. |
| `archived` | GitHub's archived flag, or `null` before a successful check. |
| `disabled` | GitHub's disabled flag, or `null` before a successful check. |
| `last_push` | GitHub's `pushed_at` UTC timestamp, or `null` if none was reported or never observed. |

`reachable` means the API returned valid public repository metadata. It does not
mean a tool was installed or tested. `unavailable` covers HTTP 404, 410, or 451,
or a repository reported private; it does not prove deletion. Authentication,
rate-limit, server, network, TLS, or malformed-response failures are `check-failed`.

Failed or unavailable checks preserve the prior successful public metadata and
its date. The README labels it as retained rather than freshly verified. Private
metadata is never copied into the snapshot, even if a local token can access it.
Entries without a matching observation show “not checked yet.”

## Local refresh

Only run a refresh when network access is authorized. It reads public metadata
through GitHub's REST API, not upstream source code or setup commands:

```sh
python3 scripts/health.py
python3 scripts/catalog.py render
python3 scripts/catalog.py check
python3 -m unittest discover -s scripts -p 'test_*.py'
```

Python 3.11+ and its standard library are sufficient. `GH_TOKEN` or `GITHUB_TOKEN`
can supply an existing GitHub token for API rate limits; never commit credentials.
Requests stay on `api.github.com`, including redirects, and TLS verification stays
enabled. If Python has no working trust store, configure a trusted CA bundle via
`SSL_CERT_FILE` rather than disabling certificate verification.

The collector updates attempt dates even when checks fail and returns success
after writing a valid snapshot; inspect its status counts and PR diff. Invalid
catalog/snapshot data or a failed file write stops the refresh. The snapshot is
replaced only after a complete write. Changed or removed catalog URLs do not
inherit unrelated observations.

## Weekly workflow

[`health.yml`](../.github/workflows/health.yml) runs on Mondays at 07:43 UTC or by
manual dispatch on the default branch. Scheduled runs can be delayed by GitHub.
It uses pinned actions and proposes only `data/health.json` and the generated
README on `automation/catalog-health`. It opens or updates a PR; it never
auto-merges, removes entries, or edits `last_reviewed`. The existing weekly
upstream-link check remains separate.

The bot uses `GITHUB_TOKEN` with contents and pull-request write permissions to
publish its branch and PR. Repository/organization settings must permit Actions
to create pull requests. Its actions-write permission dispatches `checks.yml`
against the bot branch, because `GITHUB_TOKEN`-created PRs do not automatically
trigger ordinary PR workflows. No personal token is required. Enable required
reviews and checks through GitHub branch protection; workflows alone do not
enforce review.

Review flagged repositories and failed checks before accepting a snapshot.
Corrections or removals need a separate catalog change with upstream evidence and
a [weekly changelog](../CHANGELOG.md) note. Changelog sections start on Monday in
UTC and describe catalog changes, not upstream releases. Routine health-only PRs
do not need a changelog note.
