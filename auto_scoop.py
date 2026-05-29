#!/usr/bin/env python3
"""
自动从 GitHub Trending 发现热门仓库，过滤非软件项目，
智能识别安装包/便携版/变体，利用已有哈希文件，生成符合 Scoop 规范的 manifest。
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

# 文件名中若包含这些关键词，将生成对应的变体 manifest（如 -desktop, -client）
VARIANT_KEYWORDS = ["desktop", "client", "server", "lite", "console"]


def get_token():
    return os.environ.get("GITHUB_TOKEN")


def api_get(url, token):
    headers = HEADERS.copy()
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        resp = requests.get(url, headers=headers)
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
            resp = requests.get(url)
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


def classify_arch(asset_name):
    name = asset_name.lower()
    if any(k in name for k in ("amd64", "x86_64", "x64", "win64", "64bit", "64-bit")):
        return "64bit"
    if any(k in name for k in ("arm64", "aarch64", "arm")):
        return "arm64"
    if any(k in name for k in ("386", "x86", "win32", "32bit", "32-bit")):
        return "32bit"
    return "64bit"


def extract_hash_map_from_assets(assets):
    hash_map = {}
    for a in assets:
        name = a["name"].lower()
        if name.endswith((".sha256", ".sha256sum", ".sha256.txt", ".sha256sums")):
            print(f"  🔑 发现哈希文件: {a['name']}")
            try:
                resp = requests.get(a["browser_download_url"])
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
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    hasher = hashlib.sha256()
    fd, tmp_path = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            hasher.update(chunk)
    os.unlink(tmp_path)
    return hasher.hexdigest()


def decide_manifest_name(repo, asset_name):
    """
    根据仓库名和资产文件名决定 manifest 名称。
    - 文件名含 "portable" -> repo-portable
    - 文件名含特定关键词（如 desktop） -> repo-keyword
    - 否则 -> repo
    """
    stem = Path(asset_name).stem.lower()
    # 便携版
    if re.search(r'\bportable\b', stem):
        return f"{repo}-portable"
    # 变体关键词
    for kw in VARIANT_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', stem):
            if kw not in repo.lower():  # 避免 repo 本身就含关键词时重复
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
            bin_name = Path(asset["name"]).stem + ".exe"
            manifest["bin"] = bin_name
        else:
            bin_name = Path(asset["name"]).stem + ".exe"
            manifest["bin"] = bin_name
            manifest["extract_dir"] = ""
    else:
        architecture = {}
        for arch, (asset, sha) in assets_info.items():
            url = asset["browser_download_url"]
            ext = Path(asset["name"]).suffix.lower()
            entry = {"url": url, "hash": f"sha256:{sha}"}
            if ext in (".exe", ".msi", ".msix", ".appx"):
                entry["installer"] = {"args": ["/S"]}
                bin_name = Path(asset["name"]).stem + ".exe"
                entry["bin"] = bin_name
            else:
                bin_name = Path(asset["name"]).stem + ".exe"
                entry["bin"] = bin_name
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

        version = release["tag_name"].lstrip("v")
        assets = release.get("assets", [])
        if not assets:
            print("  无发布资产，跳过")
            continue

        hash_map = extract_hash_map_from_assets(assets)

        valid_exts = (".exe", ".msi", ".msix", ".appx", ".zip", ".7z", ".tar.gz", ".tar.xz")
        candidates = []
        for a in assets:
            name = a["name"].lower()
            if name.endswith(valid_exts) and "checksum" not in name and "sha" not in name:
                candidates.append(a)

        if not candidates:
            print("  无合适的 Windows 资产，跳过")
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
                assets_info[arch] = (best, sha)

            manifest = generate_manifest(mname, version, assets_info, None, description, homepage)
            if not manifest:
                continue

            manifest_file = bucket_dir / f"{mname}.json"
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            print(f"✅ 已生成 {manifest_file.relative_to(repo_root)}")
            added += 1
            time.sleep(0.5)

    if added > 0:
        print(f"\n🎉 共生成 {added} 个新 manifest，等待 Git 操作。")
    else:
        print("没有添加新应用。")


if __name__ == "__main__":
    main()
