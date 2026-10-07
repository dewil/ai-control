"""Private persistent admission grants for the Android client."""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import uuid


_IDLE_SECONDS = 7 * 24 * 60 * 60
_TOKEN_LIFETIME_SECONDS = 30 * 24 * 60 * 60
_TOKEN_RE = re.compile(r"\A[A-Za-z0-9_-]{43}\Z")


class DeviceGrantStore:
    """Store only token digests; callers retain the opaque token capability."""

    def __init__(self, path, clock):
        self._path = Path(path).absolute()
        self._parent = self._path.parent
        self._clock = clock
        self._validate_storage(create=True)
        try:
            with self._transaction() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS device_grants (
                        token_hash BLOB PRIMARY KEY,
                        device_id TEXT NOT NULL UNIQUE,
                        issued REAL NOT NULL,
                        last_open REAL NOT NULL,
                        expires REAL NOT NULL,
                        revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
                    )"""
                )
                connection.execute("PRAGMA user_version = 1")
                self._check_database(connection)
        except (sqlite3.Error, OSError):
            raise RuntimeError("device store unavailable") from None

    def check_available(self) -> None:
        try:
            with self._transaction() as connection:
                self._check_database(connection)
        except (sqlite3.Error, OSError):
            raise RuntimeError("device store unavailable") from None

    def issue(self) -> str:
        return self.issue_grant()[0]

    def issue_grant(self) -> tuple[str, str]:
        now = self._now()
        for _ in range(3):
            # token_urlsafe(32) encodes 256 random bits without padding.
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode("ascii")).digest()
            device_id = str(uuid.uuid4())
            try:
                with self._transaction() as connection:
                    connection.execute(
                        """INSERT INTO device_grants
                           (token_hash, device_id, issued, last_open, expires, revoked)
                           VALUES (?, ?, ?, ?, ?, 0)""",
                        (digest, device_id, now, now, now + _TOKEN_LIFETIME_SECONDS),
                    )
                return token, device_id
            except sqlite3.IntegrityError:
                # A collision is extraordinarily unlikely; retry without exposing
                # token values or database constraint details.
                continue
            except (sqlite3.Error, OSError):
                raise RuntimeError("device store unavailable") from None
        raise RuntimeError("device store unavailable")

    def admit(self, token: str, *, foreground_open: bool) -> str | None:
        if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
            return None
        digest = hashlib.sha256(token.encode("ascii")).digest()
        now = self._now()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """SELECT device_id, issued, last_open, expires, revoked
                       FROM device_grants WHERE token_hash = ?""",
                    (digest,),
                ).fetchone()
                if row is None:
                    return None
                device_id, issued, last_open, expires, revoked = row
                if not self._is_active(now, issued, last_open, expires, revoked):
                    return None
                if foreground_open:
                    connection.execute(
                        """UPDATE device_grants SET last_open = ?, expires = ?
                           WHERE token_hash = ? AND revoked = 0""",
                        (now, now + _TOKEN_LIFETIME_SECONDS, digest),
                    )
                return device_id
        except (sqlite3.Error, OSError):
            raise RuntimeError("device store unavailable") from None

    def valid(self, device_id: str) -> bool:
        if not self._valid_device_id(device_id):
            return False
        now = self._now()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """SELECT issued, last_open, expires, revoked
                       FROM device_grants WHERE device_id = ?""",
                    (device_id,),
                ).fetchone()
                return row is not None and self._is_active(now, *row)
        except (sqlite3.Error, OSError):
            raise RuntimeError("device store unavailable") from None

    def revoke(self, device_id: str) -> None:
        if not self._valid_device_id(device_id):
            return
        try:
            with self._transaction() as connection:
                connection.execute(
                    "UPDATE device_grants SET revoked = 1 WHERE device_id = ?",
                    (device_id,),
                )
        except (sqlite3.Error, OSError):
            raise RuntimeError("device store unavailable") from None

    def revoke_token(self, token: str) -> bool:
        """Idempotently revoke by bearer capability for the Android logout API."""
        if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
            return False
        digest = hashlib.sha256(token.encode("ascii")).digest()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT device_id FROM device_grants WHERE token_hash = ?",
                    (digest,),
                ).fetchone()
                if row is None:
                    return False
                connection.execute(
                    "UPDATE device_grants SET revoked = 1 WHERE token_hash = ?",
                    (digest,),
                )
                return True
        except (sqlite3.Error, OSError):
            raise RuntimeError("device store unavailable") from None

    @staticmethod
    def _valid_device_id(device_id) -> bool:
        if not isinstance(device_id, str):
            return False
        try:
            return str(uuid.UUID(device_id)) == device_id
        except (ValueError, AttributeError, TypeError):
            return False

    @staticmethod
    def _is_active(now, issued, last_open, expires, revoked) -> bool:
        return (
            not revoked
            and now >= issued
            and now < expires
            and now - last_open < _IDLE_SECONDS
        )

    def _now(self) -> float:
        try:
            now = float(self._clock())
            if not math.isfinite(now):
                raise ValueError
            return now
        except Exception:
            raise RuntimeError("device store unavailable") from None

    def _validate_storage(self, *, create: bool = False) -> None:
        try:
            parent_stat = self._parent.lstat()
        except OSError:
            raise ValueError("unsafe device store") from None
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) != 0o700
        ):
            raise ValueError("unsafe device store")

        try:
            db_stat = self._path.lstat()
        except FileNotFoundError:
            if not create:
                raise RuntimeError("device store unavailable") from None
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(self._path, flags, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
            except OSError:
                raise ValueError("unsafe device store") from None
            try:
                db_stat = self._path.lstat()
            except OSError:
                raise ValueError("unsafe device store") from None
        except OSError:
            raise ValueError("unsafe device store") from None

        if (
            not stat.S_ISREG(db_stat.st_mode)
            or db_stat.st_uid != os.geteuid()
            or stat.S_IMODE(db_stat.st_mode) != 0o600
        ):
            raise ValueError("unsafe device store")

    def _connect(self) -> sqlite3.Connection:
        self._validate_storage()
        try:
            connection = sqlite3.connect(str(self._path), timeout=5, isolation_level=None)
            os.chmod(self._path, 0o600, follow_symlinks=False)
            self._validate_storage()
            return connection
        except (sqlite3.Error, OSError):
            raise RuntimeError("device store unavailable") from None

    def _transaction(self):
        return _Transaction(self)

    @staticmethod
    def _check_database(connection: sqlite3.Connection) -> None:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError("corrupt database")


class _Transaction:
    def __init__(self, store: DeviceGrantStore):
        self._store = store
        self._connection = None

    def __enter__(self):
        self._connection = self._store._connect()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            return self._connection
        except sqlite3.Error:
            self._connection.close()
            raise

    def __exit__(self, exc_type, exc, tb):
        connection = self._connection
        try:
            if exc_type is None:
                connection.commit()
            else:
                connection.rollback()
        finally:
            connection.close()
        return False
