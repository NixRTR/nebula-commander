"""
Locks %ProgramData%\\nebula-commander\\ down to SYSTEM + Administrators.

Run by the service (as LocalSystem) on every start, before anything else
touches the folder. The MSI also sets this ACL on a fresh install (see
installer/windows/Product.wxs), but enforcing it here is what fixes UPGRADES
from versions that granted every local user full control of this folder:

- The root gets owner SYSTEM and a *protected* DACL (no inheritance from
  %ProgramData%, whose default lets Users create files in subfolders).
- Every child is re-owned by SYSTEM and given exactly the inherited ACEs -
  explicitly, via SetFileSecurity, which (unlike SetNamedSecurityInfo) does not
  propagate on its own and never follows links. Owner matters: a file a user
  created stays theirs otherwise, and an owner can always rewrite its DACL.
- Junctions/symlinks under the root are deleted, never followed - an older
  version let any user plant one (e.g. pointing at C:\\Windows), and walking
  into it as SYSTEM would re-ACL whatever it points at.
- Once per hardening version, the legacy user-writable Nebula install
  (nebula\\, plus staging leftovers) is deleted so the service reinstalls a
  checksum-verified copy (nebula_install.py). Anything a user may have
  planted there is gone.
"""
from __future__ import annotations

import os
import shutil
import stat

from client.windows.shared_paths import shared_root

__all__ = ["harden_shared_root"]

_ROOT_SDDL = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
_CHILD_DIR_SDDL = "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)"
_CHILD_FILE_SDDL = "D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)"

# Bump when a future change needs the one-time cleanup to run again.
_MARKER = ".hardened-v1"
_LEGACY_DIRS = ("nebula", "nebula.staging", "nebula.old")


def _enable_privileges() -> None:
    import ntsecuritycon
    import win32api
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY,
    )
    try:
        privs = [
            (win32security.LookupPrivilegeValue(None, name), win32security.SE_PRIVILEGE_ENABLED)
            for name in (ntsecuritycon.SE_TAKE_OWNERSHIP_NAME, ntsecuritycon.SE_RESTORE_NAME)
        ]
        win32security.AdjustTokenPrivileges(token, False, privs)
    finally:
        token.Close()


def _dacl(sddl: str):
    import win32security

    sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, win32security.SDDL_REVISION_1)
    return sd.GetSecurityDescriptorDacl()


def _apply(path: str, owner, dacl, protected: bool) -> None:
    import win32security

    # Owner first (SeTakeOwnership/SeRestore make this succeed even on a file
    # whose DACL excludes SYSTEM), then the DACL as the new owner.
    sd = win32security.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorOwner(owner, False)
    win32security.SetFileSecurity(path, win32security.OWNER_SECURITY_INFORMATION, sd)

    sd = win32security.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorDacl(True, dacl, False)
    flag = (
        win32security.PROTECTED_DACL_SECURITY_INFORMATION
        if protected
        else win32security.UNPROTECTED_DACL_SECURITY_INFORMATION
    )
    win32security.SetFileSecurity(path, win32security.DACL_SECURITY_INFORMATION | flag, sd)


def _is_link(entry: os.DirEntry) -> bool:
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return entry.is_symlink() or bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _remove_link(path: str) -> None:
    # A directory junction/symlink is removed with rmdir (removes the link,
    # not the target); a file symlink with unlink.
    try:
        os.rmdir(path)
    except OSError:
        os.unlink(path)


def _harden_children(root: str, owner, dir_dacl, file_dacl, log) -> None:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as e:
            log(f"harden: cannot list {current}: {e}")
            continue
        for entry in entries:
            if _is_link(entry):
                log(f"harden: removing link/reparse point {entry.path}")
                try:
                    _remove_link(entry.path)
                except OSError as e:
                    log(f"harden: could not remove {entry.path}: {e}")
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            try:
                _apply(entry.path, owner, dir_dacl if is_dir else file_dacl, protected=False)
            except Exception as e:
                log(f"harden: could not secure {entry.path}: {e}")
            if is_dir:
                stack.append(entry.path)


def harden_shared_root(log=lambda _msg: None) -> None:
    import win32security

    root = shared_root()
    os.makedirs(root, exist_ok=True)
    _enable_privileges()
    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)

    # Root first: as soon as this lands, non-admins can no longer create or
    # replace anything under it, so the walk below can't be raced.
    _apply(root, system, _dacl(_ROOT_SDDL), protected=True)
    _harden_children(root, system, _dacl(_CHILD_DIR_SDDL), _dacl(_CHILD_FILE_SDDL), log)

    marker = os.path.join(root, _MARKER)
    if not os.path.exists(marker):
        for name in _LEGACY_DIRS:
            path = os.path.join(root, name)
            if os.path.isdir(path):
                log(f"harden: removing legacy user-writable {path}; the service will reinstall Nebula")
                shutil.rmtree(path, ignore_errors=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write("ACL hardened; legacy Nebula install removed.\n")
