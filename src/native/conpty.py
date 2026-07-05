from __future__ import annotations

import ctypes
import os
import subprocess
import threading
from ctypes import wintypes
from pathlib import Path


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # ── Constants ────────────────────────────────────────────────
    PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    STARTF_USESTDHANDLES = 0x00000100
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    # ── Structs ──────────────────────────────────────────────────

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_byte * 1),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
            ("lpAttributeList", ctypes.c_void_p),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", wintypes.BOOL),
        ]

    # ── API Declarations ────────────────────────────────────────
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.CreatePipe.restype = wintypes.BOOL

    kernel32.CreatePseudoConsole.argtypes = [
        wintypes.ULONG,  # COORD packed as DWORD: LOWORD=X, HIWORD=Y
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    kernel32.CreatePseudoConsole.restype = ctypes.c_long  # HRESULT

    kernel32.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
    kernel32.ClosePseudoConsole.restype = None

    kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL

    kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL

    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.DeleteProcThreadAttributeList.restype = None

    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOEXW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL

    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL

    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL

    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE

    kernel32.AllocConsole.restype = wintypes.BOOL
    kernel32.AllocConsole.argtypes = []

    kernel32.FreeConsole.restype = wintypes.BOOL
    kernel32.FreeConsole.argtypes = []

    kernel32.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
    kernel32.SetConsoleTitleW.restype = wintypes.BOOL

    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    STD_OUTPUT_HANDLE = -11
    STD_ERROR_HANDLE = -12
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    CONSOLE_TEXTMODE_BUFFER = 1
    CP_UTF8 = 65001


def _make_pipe() -> tuple[int, int]:
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.bInheritHandle = True
    read_handle = wintypes.HANDLE()
    write_handle = wintypes.HANDLE()
    if not kernel32.CreatePipe(
        ctypes.byref(read_handle),
        ctypes.byref(write_handle),
        ctypes.byref(sa), 0,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return read_handle.value, write_handle.value


class PseudoConsoleProcess:
    def __init__(self, cmdline: list[str], cwd: str | None = None, console_title: str = "Updater"):
        self._process_handle: int = 0
        self._thread_handle: int = 0
        self._process_id: int = 0
        self._hpcon: int = 0
        self._input_write: int = 0  # we write to this
        self._output_read: int = 0  # we read from this
        self._closed = False
        self._out_buf = bytearray()
        self._on_line: callable | None = None
        self._reader_thread: threading.Thread | None = None

        # ── Ensure a visible console ────────────────────────────
        if not kernel32.AllocConsole():
            err = ctypes.get_last_error()
            if err not in (5, 183):  # ERROR_ACCESS_DENIED / ERROR_ALREADY_EXISTS
                raise ctypes.WinError(err)
        kernel32.SetConsoleTitleW(console_title)

        # ── Create PC pipes ─────────────────────────────────────
        pc_in_read, pc_in_write = _make_pipe()    # input to PC
        pc_out_read, pc_out_write = _make_pipe()   # output from PC

        # ── Create pseudo console ───────────────────────────────
        size = 120 | (40 << 16)  # COORD packed as DWORD: LOWORD=X, HIWORD=Y
        hpcon = wintypes.HANDLE()
        hr = kernel32.CreatePseudoConsole(
            size,
            wintypes.HANDLE(pc_in_read),
            wintypes.HANDLE(pc_out_write),
            0,
            ctypes.byref(hpcon),
        )
        if hr != 0:  # S_OK = 0, failure = HRESULT
            raise ctypes.WinError(hr & 0x0000FFFF)

        self._hpcon = hpcon.value
        self._input_write = pc_in_write
        self._output_read = pc_out_read
        # close the ends we don't need
        kernel32.CloseHandle(pc_in_read)
        kernel32.CloseHandle(pc_out_write)

        # ── Create process attribute list ───────────────────────
        attr_size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(
            None, 1, 0, ctypes.byref(attr_size)
        )
        attr_buf = ctypes.create_string_buffer(attr_size.value)
        if not kernel32.InitializeProcThreadAttributeList(
            attr_buf, 1, 0, ctypes.byref(attr_size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            pc_handle = wintypes.HANDLE(self._hpcon)
            if not kernel32.UpdateProcThreadAttribute(
                attr_buf, 0,
                ctypes.c_void_p(PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE),
                ctypes.byref(pc_handle), ctypes.sizeof(pc_handle),
                None, None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())

            # ── Start process ───────────────────────────────────
            si = STARTUPINFOEXW()
            si.cb = ctypes.sizeof(STARTUPINFOEXW)
            si.lpAttributeList = ctypes.cast(attr_buf, ctypes.c_void_p)

            cmd = subprocess.list2cmdline(cmdline)
            pi = PROCESS_INFORMATION()

            if not kernel32.CreateProcessW(
                None,
                ctypes.create_unicode_buffer(cmd),
                None, None, False,
                EXTENDED_STARTUPINFO_PRESENT,
                None,
                ctypes.create_unicode_buffer(cwd) if cwd else None,
                ctypes.byref(si),
                ctypes.byref(pi),
            ):
                raise ctypes.WinError(ctypes.get_last_error())

            self._process_handle = pi.hProcess
            self._thread_handle = pi.hThread
            self._process_id = pi.dwProcessId

        finally:
            kernel32.DeleteProcThreadAttributeList(attr_buf)

        # ── Start output reader thread ────────────────────────
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()

    # ── public API ─────────────────────────────────────────────

    @property
    def pid(self) -> int:
        return self._process_id

    def write_input(self, text: str) -> None:
        if self._closed:
            return
        data = (text + "\n").encode("utf-8")
        written = wintypes.DWORD(0)
        kernel32.WriteFile(
            wintypes.HANDLE(self._input_write),
            data, len(data),
            ctypes.byref(written), None,
        )

    def set_line_callback(self, cb: callable) -> None:
        self._on_line = cb

    def wait(self) -> int:
        if self._process_handle:
            kernel32.WaitForSingleObject(
                wintypes.HANDLE(self._process_handle), 0xFFFFFFFF
            )
            exit_code = wintypes.DWORD(0)
            kernel32.GetExitCodeProcess(
                wintypes.HANDLE(self._process_handle),
                ctypes.byref(exit_code),
            )
            return exit_code.value
        return -1

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._hpcon:
            kernel32.ClosePseudoConsole(wintypes.HANDLE(self._hpcon))
            self._hpcon = 0
        for h in (self._input_write, self._output_read):
            if h:
                kernel32.CloseHandle(wintypes.HANDLE(h))
        self._input_write = 0
        self._output_read = 0
        if self._process_handle:
            kernel32.CloseHandle(wintypes.HANDLE(self._process_handle))
            self._process_handle = 0
        if self._thread_handle:
            kernel32.CloseHandle(wintypes.HANDLE(self._thread_handle))
            self._thread_handle = 0
        kernel32.FreeConsole()

    # ── internal ───────────────────────────────────────────────

    def _reader_loop(self) -> None:
        buf = ctypes.create_string_buffer(4096)
        leftover = b""
        while not self._closed:
            if self._output_read == 0:
                break
            read_n = wintypes.DWORD(0)
            ok = kernel32.ReadFile(
                wintypes.HANDLE(self._output_read),
                buf, ctypes.sizeof(buf) - 1,
                ctypes.byref(read_n), None,
            )
            if not ok or read_n.value == 0:
                break
            data = buf[: read_n.value]
            leftover = self._process_output(leftover + data)
        # flush remaining
        if leftover:
            line = leftover.decode("utf-8", errors="replace")
            if self._on_line:
                self._on_line(line.rstrip("\r\n"))

    def _process_output(self, data: bytes) -> bytes:
        text = data.decode("utf-8", errors="replace")

        # strip ANSI escape sequences (colours, cursor moves)
        import re
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)

        lines = text.split("\n")
        for line in lines[:-1]:
            stripped = line.rstrip("\r")
            if self._on_line:
                self._on_line(stripped)
        return lines[-1].encode("utf-8")
