# SPDX-License-Identifier: GPL-3.0-only
"""Refresh legacy asset paths from canonical workflow packs; --check is read-only."""
import argparse

from packs import load_workspace, synchronize_compatibility


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    _, packs = load_workspace()
    stale = synchronize_compatibility(packs, check=args.check)
    print(('Outdated aliases: ' if args.check else 'Updated aliases: ') + (', '.join(stale) or 'none'))
    return int(args.check and bool(stale))


if __name__ == '__main__':
    raise SystemExit(main())
