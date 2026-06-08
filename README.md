# Scoop Trending Bucket

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

---

# Scoop Trending Bucket 中文说明

这是一个自动从 [GitHub Trending](https://github.com/trending) 发现热门 Windows 工具，并生成 [Scoop](https://scoop.sh/) manifest 的 bucket。

## 功能

- 每天通过 GitHub Actions 自动扫描 GitHub Trending。
- 自动为 Windows release 资产生成 Scoop manifest。
- 已存在于 `bucket/` 中的软件会被跳过，避免重复添加或覆盖。
- 同一天内多次运行 Actions，会继续写入同一个当天更新分支和 PR。
- 第二天运行时，会先合并前一天及更早的自动更新 PR，再开始当天更新。
- CI 会在 Windows PowerShell 和 PowerShell Core 下校验 bucket。

## 使用方法

添加 bucket：

```powershell
scoop bucket add trending https://github.com/watersupis/scoop-trending
```

安装软件：

```powershell
scoop install trending/<app-name>
```

搜索可用软件：

```powershell
scoop search trending/
```

更新已安装软件：

```powershell
scoop update *
```

## 自动更新流程

每日工作流在 `UTC 00:00` 运行，也可以手动触发。

1. 先合并旧的自动更新 PR，但不会合并当天 PR。
2. 准备当天分支：`scoop-update-YYYY-MM-DD`。
3. 如果当天分支已经存在，就继续使用它，因此同一天多次运行会累积到同一个 PR。
4. 运行 `auto_scoop.py` 扫描 GitHub Trending 并生成 manifest。
5. 如果软件已经存在于当前分支的 `bucket/` 中，就跳过。
6. 把新 manifest 提交到当天分支。
7. 创建或复用当天的自动更新 PR。

当天 PR 不会立即合并，方便维护者当天审查或修改。下一天工作流运行时，会先合并这个 PR，再创建新一天的更新。

如果旧自动更新 PR 出现 merge conflicts，工作流会关闭该 PR 并删除其分支，避免整个 Actions 失败。

## 配置

主要配置在 [`.github/workflows/daily-update.yml`](.github/workflows/daily-update.yml)。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_APPS` | `20` | 每次运行最多生成的新 manifest 数量。 |
| `UPDATE_BRANCH_PREFIX` | `scoop-update-` | 每日更新分支前缀。 |
| `GITHUB_TOKEN` | GitHub Actions 自动提供 | 用于 GitHub API 请求和 PR 操作。 |

如果要调整过滤规则、资产选择、版本号规范化或 manifest 生成逻辑，请修改 [`auto_scoop.py`](auto_scoop.py)。

## 项目结构

```text
scoop-trending/
├── .github/workflows/    # CI 和每日更新工作流
├── bin/                  # Scoop bucket 测试入口
├── bucket/               # Scoop manifest
├── auto_scoop.py         # GitHub Trending 扫描和 manifest 生成脚本
├── Scoop-Bucket.Tests.ps1
└── README.md
```

## Manifest 说明

自动生成的 manifest 会尽量保持保守：

- 不覆盖已存在 manifest。
- JSON 文件以换行结尾，满足 Scoop style checks。
- 类似 `iii/v0.17.0` 的 GitHub release tag 会规范化为 `0.17.0`。
- 常见 Windows 架构标记会映射为 Scoop 架构：`64bit`、`32bit`、`arm64`。

## 贡献

欢迎提交 Issue 或 PR。

你可以通过 Issue 请求收录软件、报告 manifest 问题，或建议更好的过滤规则。提交 PR 时请确保 manifest 通过 Scoop schema 和 bucket CI 校验。

## 许可

本仓库中的脚本和配置使用 MIT License。各应用名称、商标和版权归其各自所有者所有。
