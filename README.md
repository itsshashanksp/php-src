
# PHP Source Release Mirror

Automated mirror of official PHP stable source releases.

**Upstream:** https://www.php.net/downloads.php  
**Source repository:** https://github.com/php/php-src

## Repository structure

The `master` branch contains only:
- README.md
- .github/workflows/php-release-sync.yml
- scripts/sync-php-releases.py

Each stable PHP release is stored in its own branch.

Example:
- `php-8.5.11`
- `php-8.5.12`
- `php-8.5.13`

## Release synchronization

GitHub Actions automatically:

1. Checks official PHP.net release metadata.
2. Identifies the latest stable release.
3. Downloads the official source archive.
4. Verifies its SHA-256 checksum.
5. Creates an independent release branch.
6. Commits the extracted PHP source.
7. Pushes the new branch to this repository.

Existing release branches are never modified.

## Supported release series

Configured in the GitHub Actions workflow.

Default: PHP 8.5.x

## Manual synchronization

Go to Actions > PHP Stable Release Sync > Run workflow.

You can optionally specify an exact PHP patch version
to import an older release.

## Branch architecture

- `master`: automation and documentation
- `php-X.Y.Z`: official PHP source distribution

Release branches have independent Git histories.

## Source and licensing

PHP source code is maintained by the PHP development team.

This repository is an unofficial automated mirror.
It is not an official PHP distribution channel.

PHP source files retain their original licensing terms.
See the LICENSE file in each release branch.

## Integrity

Downloaded source archives are verified against SHA-256
checksums supplied by PHP.net over HTTPS.

This verifies consistency with PHP.net release metadata,
but does not independently authenticate release signatures.
