#!/usr/bin/env python3
"""Sync verified official PHP 8.5 Windows x64 binary distributions."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SERIES = "8.5"
DOWNLOAD_PAGE = "https://www.php.net/downloads.php?os=windows"
RELEASE_API = "https://www.php.net/releases/index.php?json&version=8.5"
USER_AGENT = "php-windows-binary-sync/1.0"


@dataclass(frozen=True)
class Build:
    variant: str
    branch: str
    version: str
    archive: str
    url: str
    sha256: str


class DownloadsParser(HTMLParser):
    SECTIONS = {"nts-vs17-x64": "nts", "ts-vs17-x64": "ts"}

    def __init__(self) -> None:
        super().__init__()
        self.section: str | None = None
        self.link: str | None = None
        self.in_sha = False
        self.sha_text: list[str] = []
        self.results: dict[str, tuple[str, str]] = {}

    def handle_starttag(self, tag, attrs_list):
        attrs = dict(attrs_list)
        if tag == "div":
            self.section = self.SECTIONS.get(attrs.get("id", ""))
            self.link = None
        elif self.section and tag == "a":
            href = attrs.get("href", "") or ""
            name = PurePosixPath(urllib.parse.urlparse(href).path).name
            nts = "nts-" if self.section == "nts" else ""
            pattern = rf"php-{SERIES}\.\d+(?:-\d+)?-{nts}Win32-vs17-x64\.zip"
            if re.fullmatch(pattern, name):
                self.link = href
        elif self.section and tag == "span" and attrs.get("class") == "sha256":
            self.in_sha, self.sha_text = True, []

    def handle_data(self, data):
        if self.in_sha:
            self.sha_text.append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self.in_sha:
            checksum = "".join(self.sha_text).strip().lower()
            if self.section and self.link and re.fullmatch(r"[0-9a-f]{64}", checksum):
                if self.section in self.results:
                    raise ValueError(f"Duplicate {self.section} x64 binary")
                self.results[self.section] = (self.link, checksum)
            self.in_sha = False
            self.link = None
        elif tag == "div" and self.section:
            self.section, self.link = None, None


def request_bytes(url: str, timeout=60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def discover_builds() -> list[Build]:
    version = json.loads(request_bytes(RELEASE_API)).get("version", "")
    if not re.fullmatch(rf"{SERIES}\.\d+", version):
        raise ValueError(f"PHP API did not return stable {SERIES}.x")
    parser = DownloadsParser()
    parser.feed(request_bytes(DOWNLOAD_PAGE).decode())
    if set(parser.results) != {"nts", "ts"}:
        raise ValueError("Expected exactly one TS and NTS VS17 x64 binary")
    builds = []
    for variant in ("nts", "ts"):
        url, checksum = parser.results[variant]
        archive = PurePosixPath(urllib.parse.urlparse(url).path).name
        nts = "nts-" if variant == "nts" else ""
        match = re.fullmatch(
            rf"php-({SERIES}\.\d+)(?:-\d+)?-{nts}Win32-vs17-x64\.zip", archive
        )
        if not match or match.group(1) != version:
            raise ValueError(f"{variant} binary does not match stable PHP {version}")
        builds.append(Build(
            variant, f"php-{SERIES}.X-{variant}-x64", version,
            archive, url, checksum,
        ))
    return builds


def download_verify_extract(build: Build, workspace: Path) -> Path:
    archive = workspace / build.archive
    digest = hashlib.sha256()
    request = urllib.request.Request(build.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, archive.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != build.sha256:
        archive.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 verification failed for {build.archive}")

    output = workspace / build.variant
    output.mkdir()
    root = output.resolve()
    with zipfile.ZipFile(archive) as bundle:
        if not bundle.infolist():
            raise ValueError(f"Empty ZIP: {build.archive}")
        for member in bundle.infolist():
            path = PurePosixPath(member.filename.replace("\\", "/"))
            target = (output / Path(*path.parts)).resolve()
            if path.is_absolute() or ".." in path.parts or root not in (target, *target.parents):
                raise ValueError(f"Unsafe ZIP entry: {member.filename}")
        bundle.extractall(output)
    shutil.rmtree(output / ".github", ignore_errors=True)
    if not (output / "php.exe").is_file() or not (output / "ext").is_dir():
        raise ValueError(f"Incomplete distribution: {build.archive}")
    return output


def smoke_test(build: Build, directory: Path) -> None:
    php = directory / "php.exe"
    version = subprocess.run(
        [str(php), "-n", "-v"], check=True, text=True,
        capture_output=True, timeout=30,
    ).stdout
    if f"PHP {build.version}" not in version:
        raise ValueError(f"php.exe version mismatch for {build.variant}")
    expected = "true" if build.variant == "ts" else "false"
    code = (
        f"$expectedTs={expected};"
        "$ok=PHP_INT_SIZE===8&&PHP_ZTS===$expectedTs&&"
        "json_decode(json_encode(['sync'=>true]),true)['sync']===true;"
        "if(!$ok){fwrite(STDERR,'smoke test failed');exit(1);}"
        "echo PHP_VERSION,'|',PHP_INT_SIZE*8,'|',PHP_ZTS?'ts':'nts';"
    )
    result = subprocess.run(
        [str(php), "-n", "-r", code], check=True, text=True,
        capture_output=True, timeout=30,
    )
    print(f"Validated {build.archive}: {result.stdout}")


def git(*args, cwd: Path, capture=False, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, text=True,
        capture_output=capture,
    )


def copy_auth(clone: Path) -> None:
    result = git(
        "config", "--local", "--get-regexp", r"^http\..*\.extraheader$",
        cwd=ROOT, capture=True, check=False,
    )
    for line in result.stdout.splitlines():
        key, value = line.split(None, 1)
        git("config", "--local", key, value, cwd=clone)


def replace_tree(worktree: Path, source: Path) -> None:
    for entry in worktree.iterdir():
        if entry.name != ".git":
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    for entry in source.iterdir():
        target = worktree / entry.name
        shutil.copytree(entry, target) if entry.is_dir() else shutil.copy2(entry, target)


def prepare_commit(clone: Path, build: Build, source: Path) -> str | None:
    remote_ref = f"refs/remotes/origin/{build.branch}"
    exists = git(
        "show-ref", "--verify", "--quiet", remote_ref, cwd=clone, check=False
    ).returncode == 0
    if exists:
        metadata = git(
            "show", f"{remote_ref}:.php-binary-sync.json",
            cwd=clone, capture=True, check=False,
        )
        if metadata.returncode == 0:
            try:
                if json.loads(metadata.stdout).get("archive") == build.archive:
                    print(f"{build.branch} already contains {build.archive}; skipping")
                    return None
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid sync metadata on {build.branch}") from error

    worktree = clone.parent / f"worktree-{build.variant}"
    if exists:
        git("worktree", "add", "--detach", str(worktree), remote_ref, cwd=clone)
    else:
        git("worktree", "add", "--detach", str(worktree), cwd=clone)
        git("switch", "--orphan", f"sync-{build.variant}", cwd=worktree)
    replace_tree(worktree, source)
    metadata = {
        "archive": build.archive, "build_variant": f"{build.variant.upper()} x64",
        "php_version": build.version, "sha256": build.sha256,
        "upstream_url": build.url,
    }
    (worktree / ".php-binary-sync.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if (worktree / ".github" / "workflows").exists():
        raise ValueError("Refusing to import upstream workflows")
    git("add", "-A", cwd=worktree)
    git(
        "commit", "-m", f"php: import {build.version} {build.variant.upper()} x64",
        "-m", (
            f"Upstream-Archive: {build.archive}\n"
            f"Upstream-SHA256: {build.sha256}\n"
            f"Build-Variant: {build.variant.upper()} x64"
        ),
        cwd=worktree,
    )
    commit = git("rev-parse", "HEAD", cwd=worktree, capture=True).stdout.strip()
    return f"{commit}:refs/heads/{build.branch}"


def publish(builds: list[Build], sources: dict[str, Path], dry_run: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="php-windows-git-") as temp:
        clone = Path(temp) / "repository"
        git("clone", "--no-checkout", str(ROOT), str(clone), cwd=ROOT)
        origin = git("remote", "get-url", "origin", cwd=ROOT, capture=True).stdout.strip()
        git("remote", "set-url", "origin", origin, cwd=clone)
        copy_auth(clone)
        fetch = git(
            "fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*",
            cwd=clone, capture=True, check=False,
        )
        if fetch.returncode:
            raise RuntimeError(f"Authentication/fetch failed: {fetch.stderr.strip()}")
        git("config", "user.name", "github-actions[bot]", cwd=clone)
        git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=clone)
        git("config", "core.filemode", "false", cwd=clone)
        refs = [
            ref for build in builds
            if (ref := prepare_commit(clone, build, sources[build.variant]))
        ]
        if not refs:
            print("No binary branch updates are required")
        elif dry_run:
            print("Dry run prepared: " + ", ".join(ref.split(":", 1)[1] for ref in refs))
        else:
            push = git(
                "push", "--atomic", "origin", *refs,
                cwd=clone, capture=True, check=False,
            )
            if push.returncode:
                raise RuntimeError(f"Atomic non-force push failed: {push.stderr.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Windows x64 smoke tests require a Windows runner")
    builds = discover_builds()
    expected = {"php-8.5.x-nts-x64", "php-8.5.x-ts-x64"}
    if {build.branch for build in builds} != expected:
        raise AssertionError("Unexpected target branches")
    with tempfile.TemporaryDirectory(prefix="php-windows-download-") as temp:
        workspace = Path(temp)
        sources = {}
        for build in builds:
            print(f"Downloading {build.url}")
            sources[build.variant] = download_verify_extract(build, workspace)
            smoke_test(build, sources[build.variant])
        publish(builds, sources, args.dry_run)


if __name__ == "__main__":
    main()
