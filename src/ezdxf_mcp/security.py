"""Security primitives shared by the API and local cursor bridge."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def load_secret_file(
    path: Path,
    *,
    minimum_length: int = 32,
    maximum_length: int = 4096,
) -> str:
    """Read one ASCII secret without following links or accepting weak permissions."""
    initial = path.lstat()
    if stat.S_ISLNK(initial.st_mode):
        raise PermissionError(f"secret file must not be a symbolic link: {path}")
    if not stat.S_ISREG(initial.st_mode):
        raise PermissionError(f"secret path is not a regular file: {path}")
    if stat.S_IMODE(initial.st_mode) & 0o077:
        raise PermissionError(f"secret file has unsafe permissions: {path}")
    if initial.st_uid not in {0, os.geteuid()}:
        raise PermissionError(f"secret file has an unexpected owner: {path}")
    if initial.st_nlink != 1:
        raise PermissionError(f"secret file must have exactly one hard link: {path}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != initial.st_dev
            or opened.st_ino != initial.st_ino
            or not stat.S_ISREG(opened.st_mode)
        ):
            raise PermissionError(f"secret file changed while it was being opened: {path}")
        raw = os.read(descriptor, maximum_length + 1)
    finally:
        os.close(descriptor)

    if len(raw) > maximum_length:
        raise ValueError(f"secret file is unexpectedly large: {path}")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError(f"secret file must contain ASCII only: {path}") from error
    token = text.rstrip("\r\n")
    if token != token.strip() or any(character.isspace() for character in token):
        raise ValueError(f"secret must be a single token without whitespace: {path}")
    if len(token) < minimum_length:
        raise ValueError(f"secret is absent or too short: {path}")
    return token
