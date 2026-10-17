"""Windows process-tree ownership; attach while the primary thread is suspended.

An unnamed job uses KILL_ON_JOB_CLOSE, without breakaway flags. This is lifecycle
containment for trusted commands, not a filesystem/network security sandbox.
"""
import ctypes
from ctypes import wintypes


class WindowsProcessJob:
    def __init__(self, process):
        import psutil
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel, self.handle = kernel, None
        for name, restype, arguments in (
            ("CreateJobObjectW", wintypes.HANDLE, [ctypes.c_void_p, wintypes.LPCWSTR]),
            ("SetInformationJobObject", wintypes.BOOL, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]),
            ("AssignProcessToJobObject", wintypes.BOOL, [wintypes.HANDLE, wintypes.HANDLE]),
            ("OpenProcess", wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
            ("OpenThread", wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
            ("ResumeThread", wintypes.DWORD, [wintypes.HANDLE]),
            ("TerminateJobObject", wintypes.BOOL, [wintypes.HANDLE, wintypes.UINT]),
            ("CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
        ):
            function = getattr(kernel, name)
            function.restype, function.argtypes = restype, arguments
        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t), ("maximum", ctypes.c_size_t),
                ("active_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = handle
        process_handle = thread_handle = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process_handle = kernel.OpenProcess(0x0101, False, process.pid)  # SET_QUOTA | TERMINATE
            if not process_handle or not kernel.AssignProcessToJobObject(handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
            threads = psutil.Process(process.pid).threads()
            if len(threads) != 1:
                raise RuntimeError("Suspended command did not have exactly one primary thread")
            thread_handle = kernel.OpenThread(0x0002, False, threads[0].id)
            if not thread_handle or kernel.ResumeThread(thread_handle) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise
        finally:
            for opened in (thread_handle, process_handle):
                if opened:
                    kernel.CloseHandle(opened)

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            # Also terminate explicitly so both normal exit and parent-service
            # death have the same owned descendant cleanup guarantee.
            self.kernel.TerminateJobObject(handle, 1)
            self.kernel.CloseHandle(handle)
