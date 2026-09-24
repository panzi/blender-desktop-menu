# License: LGPLv2-or-later
# Author: Mathias Panzenböck

import ctypes
import errno
import struct

from typing import Callable, Any
from ctypes import c_void_p, CFUNCTYPE, POINTER, c_int, c_ulong, c_ushort, c_ubyte, Structure, _Pointer, cast
from ctypes.wintypes import LPVOID, WORD, DWORD, ULONG, LPWSTR, BOOL, LPCVOID, HLOCAL, LPCOLESTR, LPOLESTR, LPCWSTR

HRESULT = ctypes.c_uint32

FALSE = 0
TRUE = 1

# https://learn.microsoft.com/en-us/windows/win32/learnwin32/error-handling-in-com
S_OK = 0x0
S_FALSE = 0x1

CLSCTX_INPROC_SERVER = 1

class GUID(Structure):
    _fields_ = [
        ('Data1', c_ulong),
        ('Data2', c_ushort),
        ('Data3', c_ushort),
        ('Data4', c_ubyte * 8),
    ]
    Data1: c_ulong
    Data2: c_ushort
    Data3: c_ushort
    Data4: Any # XXX: no idea how to annotate this

ole32 = ctypes.windll.ole32 # type: ignore
kernel32 = ctypes.windll.kernel32 # type: ignore

CoInitialize = ole32.CoInitialize
CoInitialize.argtypes = (LPVOID, )
CoInitialize.restype = HRESULT

CoCreateInstance = ole32.CoCreateInstance
CoCreateInstance.argtypes = (POINTER(GUID), LPVOID, DWORD, POINTER(GUID), POINTER(LPVOID))
CoCreateInstance.restype = HRESULT

CoUninitialize = ole32.CoUninitialize
CoUninitialize.argtypes = ()
CoUninitialize.restype = None

FormatMessage = kernel32.FormatMessageW
FormatMessage.argtypes = (DWORD, LPCVOID, DWORD, DWORD, LPWSTR, DWORD, c_void_p)
FormatMessage.restype = DWORD

LocalFree = kernel32.LocalFree
LocalFree.argtypes = (HLOCAL, )
LocalFree.restype = HLOCAL

FACILITY_WINDOWS = 8

FORMAT_MESSAGE_ALLOCATE_BUFFER = 0x00000100
FORMAT_MESSAGE_FROM_SYSTEM = 0x00001000

def HRESULT_FACILITY(hr: int) -> int:
    return ((hr) >> 16) & 0x1fff

def HRESULT_CODE(hr: int) -> int:
    return (hr) & 0xFFFF

# See: https://learn.microsoft.com/en-us/windows/win32/cossdk/interpreting-error-codes
def get_hresult_message(hr: int) -> str:
    if FACILITY_WINDOWS == HRESULT_FACILITY(hr):
        hr = HRESULT_CODE(hr)

    pszErrMsg = ctypes.pointer(LPWSTR())
    if FormatMessage(
       FORMAT_MESSAGE_ALLOCATE_BUFFER|FORMAT_MESSAGE_FROM_SYSTEM,
       None, hr, 0, cast(pszErrMsg, LPWSTR), 0, None) != 0:
        szErrMsg = pszErrMsg.contents
        try:
            message = szErrMsg.value
        finally:
            LocalFree(szErrMsg)
    else:
        message = None

    if message is None:
        return 'unknown error'

    return message

GUID_STRUCT = struct.Struct('>LHH8b')

def make_guid(guid_bytes: bytes) -> GUID:
    guid = GUID()

    data1, data2, data3, *data4 = GUID_STRUCT.unpack(guid_bytes)

    guid.Data1 = data1
    guid.Data2 = data2
    guid.Data3 = data3
    guid.Data4[:] = data4

    return guid

CLSID_ShellLink = make_guid(b'\x00\x02\x14\x01\x00\x00\x00\x00\xC0\x00\x00\x00\x00\x00\x00\x46')
IID_IShellLinkW = make_guid(b'\x00\x02\x14\xF9\x00\x00\x00\x00\xC0\x00\x00\x00\x00\x00\x00\x46')

IID_IPersistFile = make_guid(b'\x00\x00\x01\x0b\x00\x00\x00\x00\xC0\x00\x00\x00\x00\x00\x00\x46')

class IPersistFile(Structure):
    pass

IPersistFilePtr = POINTER(IPersistFile)

class IPersistFileVtbl(Structure):
    _fields_ = [
        ('QueryInterface', CFUNCTYPE(HRESULT, IPersistFilePtr, POINTER(GUID), POINTER(LPVOID))),
        ('AddRef', CFUNCTYPE(ULONG, IPersistFilePtr)),
        ('Release', CFUNCTYPE(ULONG, IPersistFilePtr)),
        ('GetClassID', CFUNCTYPE(HRESULT, IPersistFilePtr, POINTER(GUID))),
        ('IsDirty', CFUNCTYPE(HRESULT, IPersistFilePtr)),
        ('Load', CFUNCTYPE(HRESULT, IPersistFilePtr, LPCOLESTR, DWORD)),
        ('Save', CFUNCTYPE(HRESULT, IPersistFilePtr, LPCOLESTR, BOOL)),
        ('SaveCompleted', CFUNCTYPE(HRESULT, IPersistFilePtr, LPWSTR)),
        ('GetCurFile', CFUNCTYPE(HRESULT, IPersistFilePtr, LPOLESTR)),
    ]
    QueryInterface: Callable[[_Pointer, GUID, LPVOID], int]
    Release: Callable[[_Pointer], ULONG]
    Save: Callable[[_Pointer, str, int], int]

IPersistFile._fields_ = [
    ('lpVtbl', POINTER(IPersistFileVtbl)),
]

class IShellLink(Structure):
    pass

IShellLinkPtr = POINTER(IShellLink)

class IShellLinkVtbl(Structure):
    _fields_ = [
        ('QueryInterface', CFUNCTYPE(HRESULT, IShellLinkPtr, POINTER(GUID), POINTER(LPVOID))),
        ('AddRef', CFUNCTYPE(ULONG, IShellLinkPtr)),
        ('Release', CFUNCTYPE(ULONG, IShellLinkPtr)),
        # TODO: WIN32_FIND_DATAA, See: https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-win32_find_dataa
        ('GetPath', CFUNCTYPE(HRESULT, IShellLinkPtr, LPWSTR, c_int, LPVOID, DWORD)),
        ('GetIDList', c_void_p), # TODO: What is a PCIDLIST_ABSOLUTE?
        ('SetIDList', c_void_p), # TODO: What is a PCIDLIST_ABSOLUTE?
        ('GetDescription', CFUNCTYPE(HRESULT, IShellLinkPtr, LPCWSTR, c_int)),
        ('SetDescription', CFUNCTYPE(HRESULT, IShellLinkPtr, LPWSTR)),
        ('GetWorkingDirectory', CFUNCTYPE(HRESULT, IShellLinkPtr, LPWSTR, c_int)),
        ('SetWorkingDirectory', CFUNCTYPE(HRESULT, IShellLinkPtr, LPCWSTR)),
        ('GetArguments', CFUNCTYPE(HRESULT, IShellLinkPtr, LPWSTR, c_int)),
        ('SetArguments', CFUNCTYPE(HRESULT, IShellLinkPtr, LPCWSTR)),
        ('GetHotkey', CFUNCTYPE(HRESULT, IShellLinkPtr, POINTER(WORD))),
        ('SetHotkey', CFUNCTYPE(HRESULT, IShellLinkPtr, WORD)),
        ('GetShowCmd', CFUNCTYPE(HRESULT, IShellLinkPtr, POINTER(c_int))),
        ('SetShowCmd', CFUNCTYPE(HRESULT, IShellLinkPtr, c_int)),
        ('GetIconLocation', CFUNCTYPE(HRESULT, IShellLinkPtr, LPWSTR, c_int, POINTER(c_int))),
        ('SetIconLocation', CFUNCTYPE(HRESULT, IShellLinkPtr, LPCWSTR, c_int)),
        ('SetRelativePath', CFUNCTYPE(HRESULT, IShellLinkPtr, LPCWSTR, DWORD)),
        ('Resolve', CFUNCTYPE(HRESULT, IShellLinkPtr, DWORD)),
        ('SetPath', CFUNCTYPE(HRESULT, IShellLinkPtr, LPCWSTR)),
    ]

    QueryInterface: Callable[[_Pointer, GUID, _Pointer], int]
    Release: Callable[[_Pointer], int]
    SetDescription: Callable[[_Pointer, str], int]
    SetWorkingDirectory: Callable[[_Pointer, str], int]
    SetArguments: Callable[[_Pointer, str], int]
    SetHotkey: Callable[[_Pointer, int], int]
    SetShowCmd: Callable[[_Pointer, int], int]
    SetIconLocation: Callable[[_Pointer, str, c_int], int]
    SetRelativePath: Callable[[_Pointer, str, int], int]
    Resolve: Callable[[_Pointer, int], int]
    SetPath: Callable[[_Pointer, str], int]

IShellLink._fields_ = [
    ('lpVtbl', POINTER(IShellLinkVtbl)),
]

def create_shortcut(
        target: str,
        linkname: str,
        icon: str|None = None,
        icon_index: int = 0,
        working_dir: str|None = None,
        description: str|None = None,
        arguments: str|None = None,
        hotkey: int|None = None,
        show_cmd: int|None = None,
        relative_path: str|None = None,
        resolve: int|None = None,
) -> None:
    init_res = CoInitialize(None)

    if init_res not in (S_OK, S_FALSE):
        raise OSError(errno.EINVAL, f"CoInitialize(NULL): {init_res:#x} {get_hresult_message(init_res)}")

    try:
        ppsl = ctypes.pointer(LPVOID())
        res = CoCreateInstance(CLSID_ShellLink, None, CLSCTX_INPROC_SERVER, IID_IShellLinkW, ppsl)
        if res != S_OK:
            raise OSError(errno.EINVAL, f"CoCreateInstance(CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, IID_IShellLinkW, &psl): {res:#x} {get_hresult_message(res)}")

        psl = cast(ppsl, POINTER(POINTER(IShellLink))).contents
        sl = psl.contents
        slVtbl: IShellLinkVtbl = sl.lpVtbl.contents
        try:
            pppf = ctypes.pointer(LPVOID())
            res = slVtbl.QueryInterface(psl, IID_IPersistFile, pppf)

            if res != S_OK:
                raise OSError(errno.EINVAL, f"QueryInterface(IID_IPersistFile): {init_res:#x} {get_hresult_message(res)}")

            res = slVtbl.SetPath(psl, target)
            if res != S_OK:
                raise OSError(errno.EINVAL, f"SetPath(psl, {target!r}): {res:#x} {get_hresult_message(res)}")

            if icon is not None:
                res = slVtbl.SetIconLocation(psl, icon, c_int(icon_index))
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"SetIconLocation(psl, {icon!r}, {icon_index}): {res:#x} {get_hresult_message(res)}")

            if working_dir is not None:
                res = slVtbl.SetWorkingDirectory(psl, working_dir)
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"SetWorkingDirectory(psl, {working_dir!r}): {res:#x} {get_hresult_message(res)}")

            if description is not None:
                res = slVtbl.SetDescription(psl, description)
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"SetDescription(psl, {description!r}): {res:#x} {get_hresult_message(res)}")

            if arguments is not None:
                res = slVtbl.SetArguments(psl, arguments)
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"SetArguments(psl, {arguments!r}): {res:#x} {get_hresult_message(res)}")

            if hotkey is not None:
                res = slVtbl.SetHotkey(psl, hotkey)
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"SetHotkey(psl, {hotkey:#x}): {res:#x} {get_hresult_message(res)}")

            if show_cmd is not None:
                res = slVtbl.SetShowCmd(psl, show_cmd)
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"SetShowCmd(psl, {show_cmd:#x}): {res:#x} {get_hresult_message(res)}")

            if relative_path is not None:
                res = slVtbl.SetRelativePath(psl, relative_path, 0)
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"SetRelativePath(psl, {relative_path!r}): {res:#x} {get_hresult_message(res)}")

            if resolve is not None:
                res = slVtbl.Resolve(psl, resolve)
                if res != S_OK:
                    raise OSError(errno.EINVAL, f"Resolve(psl, {resolve:#x}): {res:#x} {get_hresult_message(res)}")

            ppf = cast(pppf, POINTER(POINTER(IPersistFile))).contents
            pf = ppf.contents
            pfVtbl: IPersistFileVtbl = pf.lpVtbl.contents

            try:
                res = pfVtbl.Save(ppf, linkname, TRUE)

                if res != S_OK:
                    raise OSError(errno.EINVAL, f"Save(ppf, {linkname!r}): {res:#x} {get_hresult_message(res)}")
            finally:
                pfVtbl.Release(ppf)

        finally:
            slVtbl.Release(psl)

    finally:
        if init_res == S_OK:
            CoUninitialize()
