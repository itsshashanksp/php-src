# PHP 8.5 Windows x64 Binary Mirror

This repository maintains an automated, versioned mirror of the official PHP
8.5 Windows x64 binary distributions. It tracks both the Non Thread Safe (NTS)
and Thread Safe (TS) builds published by the PHP project.

The `automation-master` branch contains the GitHub Actions workflow,
synchronization script, and documentation. The binary distributions are kept
on two independent moving branches, rather than creating a new branch for each
patch release.

This is an independent mirror, not an official PHP distribution channel.

## Branch structure

| Branch | Purpose |
| --- | --- |
| `automation-master` | Automation workflow, synchronization script, and README |
| `php-8.5.X-nts-x64` | Latest PHP 8.5.x Windows x64 NTS binaries |
| `php-8.5.X-ts-x64` | Latest PHP 8.5.x Windows x64 TS binaries |

The `X` in each binary branch name is literal. A new branch is not created for
each patch release.

The NTS build is normally appropriate for IIS FastCGI and command-line usage.
The TS build is intended for environments that require a thread-safe PHP build,
such as supported web-server module configurations.

## Binary synchronization

The Windows synchronization workflow runs on a Windows runner and performs the
following operations:

1. Queries the official PHP release API for the latest stable PHP 8.5.x
   version.
2. Reads the official
   [PHP for Windows download page](https://www.php.net/downloads.php?os=windows)
   and selects the VS17 x64 NTS and TS binary ZIP archives.
3. Downloads each archive from the official PHP download infrastructure.
4. Verifies each ZIP against the SHA-256 checksum published alongside that
   archive before extraction.
5. Rejects unsafe ZIP paths, removes any upstream **.github** directory, and
   checks that the extracted distribution contains **php.exe** and **ext**.
6. Runs **php.exe** smoke tests that validate the PHP version, 64-bit
   architecture, expected thread-safety mode, basic CLI execution, and JSON
   encoding and decoding.
7. Prepares updates in an isolated temporary Git clone and worktrees, leaving
   the checked-out automation branch unchanged.
8. Publishes both branch updates with one atomic, non-force push.

Each binary branch starts with its own orphan history. Later PHP releases append
normal commits to that branch, preserving the complete upgrade history. If the
same upstream archive is already recorded, the update is skipped.

Every imported release includes a **.php-binary-sync.json** file containing:

- the PHP version;
- the NTS or TS x64 build variant;
- the upstream archive name and URL;
- the verified SHA-256 checksum.

The same release identity and build details are also recorded in the Git commit
message.

### Scheduled and manual runs

The **PHP Windows x64 Binary Sync** workflow runs on its configured schedule and
can also be started manually from the repository's Actions page.

Manual runs provide a **dry_run** option. A dry run discovers, downloads,
verifies, extracts, tests, and prepares the current release without pushing any
branch updates.

## Windows installation

### Clone the NTS distribution

The NTS branch is the usual choice for PHP hosted through IIS FastCGI:

~~~powershell
git clone --single-branch --branch php-8.5.X-nts-x64 `
  https://github.com/itsshashanksp/php-src.git C:\PHP-Dev
~~~

Use the TS branch instead only when the target environment specifically
requires a thread-safe PHP build.

### Update an existing checkout

~~~powershell
cd C:\PHP-Dev
git pull --ff-only
.\php.exe -v
~~~

Because updates are appended without rewriting branch history, an existing
clone can be advanced with a fast-forward-only pull.

For production IIS deployments, do not automatically update the files used by
an active PHP runtime. Pull or clone the new version into a staging location,
apply the required configuration, test the application and extensions, and
then switch the IIS/FastCGI configuration through a controlled deployment
process with an appropriate rollback plan.

## Configuration and runtime requirements

PHP's Windows builds require the supported Microsoft Visual C++ Redistributable
for Visual Studio 2015–2022. Install and maintain the x64 runtime according to
the requirements documented on the official PHP for Windows download page.

The mirrored distribution does not manage local PHP configuration. Maintain
environment-specific files such as **php.ini**, application secrets, extension
settings, certificates, logs, and temporary directories outside the tracked
checkout or through a separate deployment process. Review configuration and
extension compatibility before every PHP upgrade.

## Security and limitations

- Archive integrity is checked with the SHA-256 value published by PHP over
  HTTPS. This detects corruption or a mismatch with the published artifact, but
  it is not an independent code-signing or provenance system.
- The repository stores complete Windows distributions as ordinary Git blobs.
  Retaining every upgrade commit causes repository size to grow as new binary
  versions are imported. Repository size should be monitored against GitHub's
  repository limits and recommendations.
- Windows executable and DLL files do not depend on Git's Unix executable bit.
  Git records and transfers their binary contents normally.
- The workflow validates the bundled CLI and JSON functionality. It does not
  test a specific application, IIS configuration, third-party extension, or
  production deployment.
- Consumers remain responsible for PHP configuration, runtime dependencies,
  application testing, operational rollout, and rollback procedures.

## Licensing and attribution

PHP and the official Windows builds are produced by the PHP project and its
contributors. Files mirrored on the binary branches retain their upstream
copyright notices and licensing terms. Refer to the licensing files included
in each distribution and the [official PHP website](https://www.php.net/) for
authoritative project information.

This repository is independently operated and is not affiliated with or
endorsed by the PHP project.
