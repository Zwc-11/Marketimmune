"""Send Ctrl+C only after verifying the complete Windows console process group.

Used to stop a paper runner gracefully so its gzip recordings and checkpoints close.
Pass every expected process ID, including any venv launcher and hosting PowerShell.
The helper adds its own PID; an unexpected console participant aborts the operation.
"""

from __future__ import annotations

import argparse
import ctypes
import os
from ctypes import wintypes


def interrupt(target: int, expected: set[int], *, dry_run: bool = False) -> list[int]:
    if os.name != "nt":
        raise OSError("This helper requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.AttachConsole.argtypes = [wintypes.DWORD]
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.GetConsoleProcessList.restype = wintypes.DWORD
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
    kernel.FreeConsole()
    if not kernel.AttachConsole(target):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        processes = (wintypes.DWORD * 256)()
        count = kernel.GetConsoleProcessList(processes, len(processes))
        if not 0 < count <= len(processes):
            raise RuntimeError("Cannot enumerate the entire console group")
        found = set(processes[:count])
        if found != expected | {os.getpid()}:
            raise RuntimeError(f"Unexpected console participants: {sorted(found)}; expected {sorted(expected)} plus helper")
        if not dry_run:
            if not kernel.SetConsoleCtrlHandler(None, True):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.GenerateConsoleCtrlEvent(0, 0):
                raise ctypes.WinError(ctypes.get_last_error())
        return sorted(found)
    finally:
        kernel.FreeConsole()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=int)
    parser.add_argument("--expected", nargs="+", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(interrupt(args.target, set(args.expected), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
