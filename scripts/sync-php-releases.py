
#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
SERIES = os.getenv("PHP_SERIES", "8.5")
REQUESTED_VERSION = os.getenv("PHP_VERSION", "").strip()

API = "https://www.php.net/releases/index.php"
DOWNLOADS = "https://www.php.net/distributions/"


def git(*args, cwd=ROOT, capture=False):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "PHP-Release-Mirror/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def get_release():
    version_arg = REQUESTED_VERSION or SERIES

    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version_arg):
        raise ValueError("Invalid PHP version")

    if REQUESTED_VERSION and not REQUESTED_VERSION.startswith(
        SERIES + "."
    ):
        raise ValueError("Version is outside configured series")

    metadata = fetch_json(
        f"{API}?json&version={version_arg}"
    )

    version = metadata["version"]

    if not re.fullmatch(
        rf"{re.escape(SERIES)}\.\d+", version
    ):
        raise ValueError(
            f"Not a stable release in {SERIES}: {version}"
        )

    if REQUESTED_VERSION and version != REQUESTED_VERSION:
        raise ValueError("PHP.net returned a different version")

    filename = f"php-{version}.tar.gz"

    matches = [
        source for source in metadata["source"]
        if source.get("filename") == filename
    ]

    if len(matches) != 1:
        raise ValueError("Expected source archive not found")

    checksum = matches[0]["sha256"].lower()

    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid SHA-256 checksum")

    return version, filename, checksum


def branch_exists(branch):
    result = git(
        "ls-remote",
        "--exit-code",
        "--heads",
        "origin",
        f"refs/heads/{branch}",
        capture=True,
    )
    return bool(result.stdout.strip())


def download_archive(filename, destination):
    request = urllib.request.Request(
        DOWNLOADS + filename,
        headers={"User-Agent": "PHP-Release-Mirror/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def verify_archive(path, expected):
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(
            lambda: stream.read(1024 * 1024), b""
        ):
            digest.update(chunk)

    if digest.hexdigest() != expected:
        raise ValueError("Archive SHA-256 verification failed")


def extract_archive(archive, directory, version):
    prefix = f"php-{version}"

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name

            if name != prefix and not name.startswith(
                prefix + "/"
            ):
                raise ValueError(
                    f"Unexpected archive path: {name}"
                )

            if not (member.isfile() or member.isdir()):
                raise ValueError(
                    f"Unsupported archive entry: {name}"
                )

        tar.extractall(directory, filter="data")

    source = directory / prefix

    if not source.is_dir():
        raise ValueError("Extracted source not found")

    return source


def publish_branch(source, branch):
    with tempfile.TemporaryDirectory() as temp:
        worktree = Path(temp) / "release"

        git("worktree", "add", "--detach", str(worktree), "HEAD")

        try:
            git("switch", "--orphan", branch, cwd=worktree)

            git(
                "rm", "-rf", "--ignore-unmatch", ".",
                cwd=worktree,
            )
            git("clean", "-fdx", cwd=worktree)

            shutil.copytree(
                source,
                worktree,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".github"),
            )

            git("add", "-A", cwd=worktree)

            git(
                "commit",
                "-m",
                f"release: import official PHP {branch[4:]}",
                cwd=worktree,
            )

            # No force push. Existing branches are protected.
            git(
                "push",
                "origin",
                f"HEAD:refs/heads/{branch}",
                cwd=worktree,
            )

        finally:
            git(
                "worktree", "remove", "--force",
                str(worktree),
            )


def main():
    version, filename, checksum = get_release()
    branch = f"php-{version}"

    print(f"Official PHP release: {version}")

    # git ls-remote --exit-code returns 2 when absent.
    result = subprocess.run(
        [
            "git", "ls-remote", "--exit-code",
            "--heads", "origin", f"refs/heads/{branch}"
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"Branch {branch} already exists. Skipping.")
        return

    if result.returncode != 2:
        raise RuntimeError(
            f"Unable to check remote branch: {result.stderr}"
        )

    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        archive = directory / filename

        print(f"Downloading {filename}")
        download_archive(filename, archive)

        print("Verifying official SHA-256")
        verify_archive(archive, checksum)

        print("Extracting PHP source")
        source = extract_archive(
            archive, directory, version
        )

        print(f"Creating release branch {branch}")
        publish_branch(source, branch)

    print(f"Successfully published {branch}")


if __name__ == "__main__":
    main()
