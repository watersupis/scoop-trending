# 🚀Scoop Bucket Trending

自动追踪 [GitHub Trending](https://github.com/trending) 上的热门仓库，并维护为一个 [Scoop](https://scoop.sh/) bucket，让你能用一条命令安装当前最火的开源工具。

## ✨ 特性

- ⏰ **每日自动更新** – 通过 GitHub Actions 定时抓取 Trending，生成符合 Scoop 规范的 manifest。
- 📦 **开箱即用** – 只需添加本 bucket，即可 `scoop install` 热门软件。
- 🤖 **全自动化** – 无需手动维护，机器人会自动发现新项目、计算哈希、提交文件。
- 🧹 **智能去重** – 已存在的应用不会被重复添加。
- 🧪 **安全可控** – 默认采用静默安装参数 (`/S`)，可自行修改 manifest 调整安装行为。

## 📥 使用方法

### 1. 添加 bucket
```bash
scoop bucket add trending https://github.com/watersupis/scoop-trending
```

### 2. 安装应用
```bash
scoop install <app-name>
```
应用名称即为 GitHub 仓库名（如 PowerToys、fd、lazygit 等）。

查看当前 bucket 中所有可用应用：

```bash
scoop search trending/
```

### 3. 更新应用
```bash
scoop update *
```
每次运行都会自动拉取 bucket 的最新 manifest，获取最新版本。

## 🔄 工作流程
触发：每天 UTC 0:00 自动执行（可手动触发）。

数据源：https://github.com/trending?since=daily

处理逻辑：

抓取 Trending 页面所有仓库。
逐个检查是否已存在于 bucket 中。
对新仓库获取最新 Release，选择 Windows 资产（.exe/.msi/.zip 等）。
下载文件并计算 SHA256 哈希。
生成 manifest JSON 并提交到仓库。
推送至远程，完成更新。
每次最多添加数量：可通过 MAX_APPS 环境变量控制（默认 3 个），避免单次提交过多。

## 📁 项目结构
```text
watersupis/Trending/
├── .github/workflows/    # 自动更新工作流
├── auto_scoop.py         # 核心脚本：抓取 Trending 并生成 manifest
├── README.md
├── *.json                # 各个应用的 Scoop manifest 文件
└── ...                   # 其他原有文件
```

## ⚙️ 自定义配置
你可以 fork 本项目，然后在 Actions 的 workflow 文件中修改环境变量：

变量名	作用	默认值
MAX_APPS	每次运行最多添加的新应用数	3
GITHUB_TOKEN	自动注入，无需手动设置	-
如果想调整数据源或过滤规则，可直接修改 auto_scoop.py。

## 🤝 贡献
欢迎提交 Issue 或 PR！

如果你希望某个工具被收录，可以新建 Issue 提供仓库链接。

如果某个 manifest 安装有问题，欢迎 PR 修正。

也欢迎贡献更多数据源。

## 📄 许可
本项目中的脚本及配置采用 MIT License 开源。
各个应用的商标、版权归其各自所有者所有，manifest 文件仅提供安装便利。
