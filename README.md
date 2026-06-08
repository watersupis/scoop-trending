# Scoop Trending Bucket

[中文说明](README.zh-CN.md)

A Scoop bucket that discovers popular Windows-friendly projects from [GitHub Trending](https://github.com/trending) and turns their latest releases into Scoop manifests.

## Features

- Daily GitHub Trending scan via GitHub Actions.
- Automatic Scoop manifest generation for Windows release assets.
- Duplicate protection for apps already present in `bucket/`.
- Same-day updates are accumulated in one daily pull request.
- Older daily update pull requests are merged before the next day's update starts.
- Scoop CI validation runs on Windows PowerShell and PowerShell Core.

## Usage

Add the bucket:

```powershell
scoop bucket add trending https://github.com/watersupis/scoop-trending
```

Install an app:

```powershell
scoop install trending/<app-name>
```

Search available apps:

```powershell
scoop search trending/
```

Update installed apps:

```powershell
scoop update *
```

## Automation Flow

The daily workflow runs at `00:00 UTC` and can also be started manually.

1. Merge previous auto-update pull requests whose branch is older than today's branch.
2. Prepare today's branch, named `scoop-update-YYYY-MM-DD`.
3. If today's branch already exists, continue from it so repeated runs on the same day accumulate changes.
4. Run `auto_scoop.py` to scan GitHub Trending and generate new manifests.
5. Skip any software already present in the current branch's `bucket/` directory.
6. Commit generated manifests to today's branch.
7. Create or reuse the daily auto-update pull request.

Today's pull request is not merged immediately. It is kept open during the day so maintainers can review or edit it, then the next scheduled run merges it before creating the new day's update.

If an older auto-update PR has merge conflicts, the workflow closes it and deletes its branch instead of failing the whole run.

## Configuration

The main settings live in [`.github/workflows/daily-update.yml`](.github/workflows/daily-update.yml).

| Variable | Default | Description |
| --- | --- | --- |
| `MAX_APPS` | `20` | Maximum number of new manifests generated per run. |
| `UPDATE_BRANCH_PREFIX` | `scoop-update-` | Prefix for daily update branches. |
| `GITHUB_TOKEN` | Provided by GitHub Actions | Used for GitHub API requests and PR operations. |

To change filtering rules, asset selection, version normalization, or manifest generation, edit [`auto_scoop.py`](auto_scoop.py).

## Project Layout

```text
scoop-trending/
├── .github/workflows/    # CI and daily update workflows
├── bin/                  # Scoop bucket test entrypoint
├── bucket/               # Scoop manifests
├── auto_scoop.py         # GitHub Trending scanner and manifest generator
├── Scoop-Bucket.Tests.ps1
└── README.md
```

## Manifest Notes

Generated manifests are intentionally conservative:

- Existing manifests are not overwritten.
- Generated JSON files end with a newline for Scoop style checks.
- GitHub release tags such as `iii/v0.17.0` are normalized to Scoop-safe versions such as `0.17.0`.
- Common Windows architecture markers are mapped to Scoop architectures: `64bit`, `32bit`, and `arm64`.

## Contributing

Issues and pull requests are welcome.

Use an issue to request a package, report a broken manifest, or suggest a better filtering rule. Pull requests should keep manifests valid against Scoop's schema and pass the bucket CI checks.

## License

The scripts and configuration in this repository are licensed under the MIT License. Application names, trademarks, and copyrights belong to their respective owners.
