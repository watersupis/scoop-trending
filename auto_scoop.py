#!/usr/bin/env python3
"""
自动从 GitHub Trending 发现热门仓库，过滤非软件项目，
仅挑选 Windows 安装包/压缩包，利用已有哈希，生成 Scoop manifest。
"""

import os
import re
import json
import hashlib
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import requests
from pyquery import PyQuery as pq

GITHUB_API = "https://api.github.com"
BASE_URL = "https://github.com/trending"
HEADERS = {"Accept": "application/vnd.github.v3+json"}

BUCKET_SUBDIR = "bucket"

SKIP_LANGUAGES = {
    "markdown", "html", "css", "shell", "dockerfile",
    "makefile", "roff", "tex", "powershell",
}

SKIP_TOPICS = {"awesome-list", "cheatsheet", "config", "dotfiles"}

VARIANT_KEYWORDS = ["desktop", "client", "server", "lite", "console"]

NON_WINDOWS_TERMS = [
    "darwin", "mac", "linux", "android", "ios",
    "freebsd", "openbsd", "solaris", "aix", "hpux",
    "snap", "appimage", "flatpak"
]


def get_token():
    return os.environ.get("GITHUB_TOKEN")


def api_get(url, token):
    headers = HEADERS.copy()
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        print(f"  ⚠️ API 请求失败 ({e.response.status_code}): {url}")
        return None
    except Exception as e:
        print(f"  ⚠️ 请求异常: {e}")
        return None


def fetch_trending_repos(periods):
    all_repos = set()
    for period in periods:
        url = f"{BASE_URL}?since={period}"
        print(f"  📡 正在抓取: {url}")
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"    ⚠️ 抓取失败: {e}")
            continue

        doc = pq(resp.text)
        count = 0
        for article in doc("article.Box-row").items():
            h2 = article("h2 a")
            if h2:
                text = h2.text().strip().replace(" ", "").replace("\n", "")
                if "/" in text:
                    all_repos.add(text)
                    count += 1
        print(f"    获取到 {count} 个仓库")
    return list(all_repos)


def get_repo_info(owner, repo, token):
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    return api_get(url, token)


def is_software_project(repo_info):
    if not repo_info:
        return False
    language = (repo_info.get("language") or "").lower()
    if language in SKIP_LANGUAGES:
        print(f"    🚫 语言排除 ({language})")
        return False
    topics = [t.lower() for t in repo_info.get("topics", [])]
    if any(t in SKIP_TOPICS for t in topics):
        print(f"    🚫 主题排除")
        return False
    if repo_info.get("archived", False):
        print("    🚫 已归档")
        return False
    return True


def get_latest_release(owner, repo, token):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases/latest"
    return api_get(url, token)


def is_windows_asset(name):
    name_lower = name.lower()
    for term in NON_WINDOWS_TERMS:
        if term in name_lower:
            return False
    win_exts = (".exe", ".msi", ".msix", ".appx", ".zip", ".7z", ".tar.gz", ".tar.xz", ".tgz")
    return name_lower.endswith(win_exts)


def classify_arch(asset_name):
    name = asset_name.lower()
    if any(k in name for k in ("arm64", "aarch64", "arm")):
        return "arm64"
    if any(k in name for k in ("i686", "i386", "386", "x86", "win32", "32bit", "32-bit")):
        return "32bit"
    if any(k in name for k in ("amd64", "x86_64", "x64", "win64", "64bit", "64-bit")):
        return "64bit"
    return "64bit"


def normalize_version(tag_name):
    version = tag_name.rsplit("/", 1)[-1]
    return version[1:] if version.lower().startswith("v") else version


def extract_hash_map_from_assets(assets):
    hash_map = {}
    for a in assets:
        name = a["name"].lower()
        if name.endswith((".sha256", ".sha256sum", ".sha256.txt", ".sha256sums")):
            print(f"  🔑 发现哈希文件: {a['name']}")
            try:
                resp = requests.get(a["browser_download_url"], timeout=30)
                resp.raise_for_status()
                content = resp.text
            except Exception as e:
                print(f"    ⚠️ 下载哈希文件失败: {e}")
                continue

            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    h = parts[0].lower()
                    if re.fullmatch(r"[0-9a-f]{64}", h):
                        fname = parts[-1].strip("*")
                        hash_map[fname.lower()] = h
    return hash_map


def get_sha256(url, filename, hash_map):
    filename_lower = filename.lower()
    if filename_lower in hash_map:
        h = hash_map[filename_lower]
        print(f"  ✅ 使用已有哈希: {h}")
        return h
    print(f"  ⬇️ 下载计算哈希: {url}")
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"    ❌ 下载失败: {e}")
        return None
    hasher = hashlib.sha256()
    fd, tmp_path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                hasher.update(chunk)
    except Exception as e:
        print(f"    ❌ 处理下载内容失败: {e}")
        os.unlink(tmp_path)
        return None
    os.unlink(tmp_path)
    return hasher.hexdigest()


def decide_manifest_name(repo, asset_name):
    stem = Path(asset_name).stem.lower()
    if re.search(r'\bportable\b', stem):
        return f"{repo}-portable"
    for kw in VARIANT_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', stem):
            if kw not in repo.lower():
                return f"{repo}-{kw}"
    return repo


def choose_best_asset_for_arch(assets_list):
    for a in assets_list:
        if a["name"].lower().endswith((".exe", ".msi", ".msix", ".appx")):
            return a
    for a in assets_list:
        if a["name"].lower().endswith((".zip", ".7z", ".tar.gz", ".tar.xz")):
            return a
    return assets_list[0]


def generate_manifest(app_name, version, assets_info, description, homepage):
    manifest = {
        "version": version,
        "description": description,
        "homepage": homepage,
        "license": "unknown",
    }
    if not assets_info:
        return None

    if len(assets_info) == 1:
        arch, (asset, sha) = next(iter(assets_info.items()))
        url = asset["browser_download_url"]
        ext = Path(asset["name"]).suffix.lower()
        manifest["url"] = url
        manifest["hash"] = f"sha256:{sha}"
        if ext in (".exe", ".msi", ".msix", ".appx"):
            manifest["installer"] = {"args": ["/S"]}
            manifest["bin"] = Path(asset["name"]).stem + ".exe"
        else:
            manifest["bin"] = Path(asset["name"]).stem + ".exe"
            manifest["extract_dir"] = ""
    else:
        architecture = {}
        for arch, (asset, sha) in assets_info.items():
            url = asset["browser_download_url"]
            ext = Path(asset["name"]).suffix.lower()
            entry = {"url": url, "hash": f"sha256:{sha}"}
            if ext in (".exe", ".msi", ".msix", ".appx"):
                entry["installer"] = {"args": ["/S"]}
                entry["bin"] = Path(asset["name"]).stem + ".exe"
            else:
                entry["bin"] = Path(asset["name"]).stem + ".exe"
                entry["extract_dir"] = ""
            architecture[arch] = entry
        manifest["architecture"] = architecture
    return manifest


def is_existing(repo_full, bucket_subdir):
    if not bucket_subdir.exists():
        return None
    for f in bucket_subdir.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if "homepage" in data and repo_full in data["homepage"]:
                return f.stem
            if "url" in data and repo_full in data["url"]:
                return f.stem
            for arch in data.get("architecture", {}).values():
                if "url" in arch and repo_full in arch["url"]:
                    return f.stem
        except Exception:
            continue
    return None


def main():
    repo_root = Path.cwd()
    bucket_dir = repo_root / BUCKET_SUBDIR
    bucket_dir.mkdir(exist_ok=True)

    token = get_token()
    periods_str = os.environ.get("TRENDING_PERIODS", "daily,weekly,monthly")
    periods = [p.strip() for p in periods_str.split(",") if p.strip()]

    print(f"🌐 抓取 GitHub Trending (周期: {', '.join(periods)}) ...")
    trending = fetch_trending_repos(periods)
    print(f"📊 去重后共 {len(trending)} 个热门仓库")

    max_new = int(os.environ.get("MAX_APPS", "3"))
    added = 0

    for repo_full in trending:
        if added >= max_new:
            break

        try:
            existing = is_existing(repo_full, bucket_dir)
            if existing:
                print(f"⏭️  {repo_full} 已存在 ({existing})")
                continue

            print(f"\n🔍 检查新项目: {repo_full}")
            owner, repo = repo_full.split("/")

            repo_info = get_repo_info(owner, repo, token)
            if not repo_info:
                print("  无法获取仓库信息，跳过")
                continue
            if not is_software_project(repo_info):
                continue

            release = get_latest_release(owner, repo, token)
            if not release:
                print("  无法获取 release，跳过")
                continue

            version = normalize_version(release["tag_name"])
            assets = release.get("assets", [])
            if not assets:
                print("  无发布资产，跳过")
                continue

            hash_map = extract_hash_map_from_assets(assets)

            # 挑选 Windows 资产
            candidates = []
            for a in assets:
                name = a["name"]
                if is_windows_asset(name) and "checksum" not in name.lower() and "sha" not in name.lower():
                    candidates.append(a)

            if not candidates:
                print("  无 Windows 资产，跳过")
                continue

            # 按 manifest 名和架构分组
            manifest_groups = defaultdict(lambda: defaultdict(list))
            for a in candidates:
                mname = decide_manifest_name(repo, a["name"])
                arch = classify_arch(a["name"])
                manifest_groups[mname][arch].append(a)

            description = (repo_info.get("description") or "")[:200]
            homepage = repo_info.get("html_url") or f"https://github.com/{owner}/{repo}"

            for mname, arch_dict in manifest_groups.items():
                assets_info = {}
                for arch, asset_list in arch_dict.items():
                    best = choose_best_asset_for_arch(asset_list)
                    sha = get_sha256(best["browser_download_url"], best["name"], hash_map)
                    if sha is None:
                        print(f"    ⚠️ 无法获取哈希，跳过架构 {arch} 的 {best['name']}")
                        continue
                    assets_info[arch] = (best, sha)

                if not assets_info:
                    print(f"  ⚠️ 无有效哈希，跳过 manifest: {mname}")
                    continue

                # 修正：去掉多余的 None 参数
                manifest = generate_manifest(mname, version, assets_info, description, homepage)
                if not manifest:
                    continue

                manifest_file = bucket_dir / f"{mname}.json"
                if manifest_file.exists():
                    print(f"⏭️  {manifest_file.name} 已存在，跳过")
                    continue
                with open(manifest_file, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
                    f.write("\n")
                print(f"✅ 已生成 {manifest_file.relative_to(repo_root)}")
                added += 1
                time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ 处理仓库 {repo_full} 时发生未预期错误: {e}")
            continue

    if added > 0:
        print(f"\n🎉 共生成 {added} 个新 manifest，等待 Git 操作。")
    else:
        print("没有添加新应用。")


if __name__ == "__main__":
    main()
