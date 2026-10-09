"""Extract single-file KTRU ZIPs beside their archives, then delete each ZIP.

Usage: python scripts/extract_ktru.py [directory] [--dry-run]
The default directory is data/КТРУ/КТРУ, relative to the project root.
"""

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile
from zipfile import BadZipFile, ZipFile


DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "КТРУ" / "КТРУ"


def extract_archive(archive: Path, dry_run: bool = False) -> None:
    with ZipFile(archive) as zipped:
        files = [entry for entry in zipped.infolist() if not entry.is_dir()]
        if len(files) != 1:
            raise ValueError(f"expected one file, found {len(files)}")
        entry = files[0]
        # Keep the original filename, placing it directly beside the ZIP.
        name = entry.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if name in ("", ".", ".."):
            raise ValueError("invalid filename in archive")
        target = archive.parent / name
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"destination already exists: {target}")
        if dry_run:
            print(f"Would extract {archive} -> {target} and delete ZIP")
            return

        # Reading to EOF validates the ZIP CRC. Publish only a complete file.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=archive.parent, delete=False) as output:
                temporary = Path(output.name)
                with zipped.open(entry) as source:
                    shutil.copyfileobj(source, output)
            # An exclusive link prevents overwriting even if a file appeared
            # after the destination check above.
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    archive.unlink()
    print(f"Extracted {target}; deleted {archive.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=DEFAULT_DIRECTORY)
    parser.add_argument("--dry-run", action="store_true", help="preview without changing files")
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error(f"not a directory: {args.directory}")

    archives = sorted(
        path for path in args.directory.rglob("*")
        if path.suffix.lower() == ".zip" and path.is_file() and not path.is_symlink()
    )
    failed = 0
    for archive in archives:
        try:
            extract_archive(archive, args.dry_run)
        except (OSError, ValueError, BadZipFile, RuntimeError, NotImplementedError) as error:
            failed += 1
            print(f"Kept {archive}: {error}", file=sys.stderr)
    print(f"{'Previewed' if args.dry_run else 'Extracted'} {len(archives) - failed} ZIPs; {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
