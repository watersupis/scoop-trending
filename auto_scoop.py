#!/usr/bin/env python3
"""
自动从 GitHub Trending (每日/每周/每月) 发现热门仓库，
过滤非软件项目，将 manifest 生成到 bucket/ 目录。
所有 Git 操作由外部 workflow 负责。
"""

import os
import re
import json
import hashlib
import sys
import tempfile
import time
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


def choose_assets(assets):
    exts = (".exe", ".msi", ".zip", ".7z", ".msix", ".appx")
    selected = []
    for a in assets:
        name = a["name"].lower()
        if name.endswith(exts) and "checksum" not in name and "sha" not in name:
            selected.append(a)
    if not selected:
        return {}

    arch_map = {"64bit": [], "32bit": []}
    for a in selected:
        name = a["name"].lower()
        if "x64" in name or "win64" in name or "amd64" in name:
            arch_map["64bit"].append(a)
        elif "x86" in name or "win32" in name or "386" in name:
            arch_map["32bit"].append(a)
        else:
            arch_map["64bit"].append(a)

    result = {}
    if arch_map["64bit"]:
        result["64bit"] = arch_map["64bit"][0]
    if arch_map["32bit"]:
        result["32bit"] = arch_map["32bit"][0]
    if not result:
        result["64bit"] = selected[0]
    return result


def download_and_hash(url):
    print(f"  ⬇️ 下载 {url} ...")
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


def generate_manifest(app_name, version, assets_info, bin_name, description, homepage):
    manifest = {
        "version": version,
        "description": description,
        "homepage": homepage,
        "license": "unknown",
    }
    architecture = {}
    for arch, (asset, sha) in assets_info.items():
        url = asset["browser_download_url"]
        ext = Path(asset["name"]).suffix.lower()
        entry = {"url": url, "hash": f"sha256:{sha}"}
        if ext in (".exe", ".msi", ".msix", ".appx"):
            entry["installer"] = {"args": ["/S"]}
            if bin_name:
                entry["bin"] = bin_name
        else:
            if not bin_name:
                base = re.sub(rf"{re.escape(ext)}$", "", asset["name"])
                bin_name = base + ".exe"
            entry["bin"] = bin_name
        architecture[arch] = entry

    if len(architecture) == 1 and "64bit" in architecture:
        manifest.update(architecture["64bit"])
    else:
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

        assets_by_arch = choose_assets(assets)
        if not assets_by_arch:
            print("  无合适的 Windows 资产，跳过")
            continue

        assets_info = {}
        for arch, asset in assets_by_arch.items():
            print(f"  {arch}: {asset['name']}")
            sha = download_and_hash(asset["browser_download_url"])
            assets_info[arch] = (asset, sha)

        description = (repo_info.get("description") or "")[:200]
        homepage = repo_info.get("html_url") or f"https://github.com/{owner}/{repo}"
        manifest = generate_manifest(repo, version, assets_info, None, description, homepage)

        manifest_file = bucket_dir / f"{repo}.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"✅ 已生成 {manifest_file.relative_to(repo_root)}")
        added += 1
        time.sleep(1)

    if added > 0:
        print(f"\n🎉 共生成 {added} 个新 manifest，等待外部 Git 提交。")
    else:
        print("没有添加新应用。")


if __name__ == "__main__":
    main()
