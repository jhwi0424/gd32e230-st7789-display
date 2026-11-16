"""Windows SetupAPI and WinUSB transport for CMSIS-DAP v2 (no pip dependencies)."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import datetime
import json
from pathlib import Path
import struct
import time


class GUID(c.Structure):
    _fields_ = [("data1", w.DWORD), ("data2", w.WORD), ("data3", w.WORD), ("data4", c.c_ubyte * 8)]


class InterfaceData(c.Structure):
    _fields_ = [("size", w.DWORD), ("guid", GUID), ("flags", w.DWORD), ("reserved", c.c_size_t)]


class PipeInfo(c.Structure):
    _fields_ = [("kind", c.c_int), ("id", c.c_ubyte), ("max_packet", w.USHORT), ("interval", c.c_ubyte)]


def configure_dlls():
    setup = c.WinDLL("setupapi", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    usb = c.WinDLL("winusb", use_last_error=True)
    definitions = [
        (setup, "SetupDiGetClassDevsW", [c.POINTER(GUID), w.LPCWSTR, w.HWND, w.DWORD], w.HANDLE),
        (setup, "SetupDiEnumDeviceInterfaces", [w.HANDLE, c.c_void_p, c.POINTER(GUID), w.DWORD, c.POINTER(InterfaceData)], w.BOOL),
        (setup, "SetupDiGetDeviceInterfaceDetailW", [w.HANDLE, c.POINTER(InterfaceData), c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p], w.BOOL),
        (setup, "SetupDiDestroyDeviceInfoList", [w.HANDLE], w.BOOL),
        (kernel, "CreateFileW", [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        (kernel, "CloseHandle", [w.HANDLE], w.BOOL),
        (usb, "WinUsb_Initialize", [w.HANDLE, c.POINTER(w.HANDLE)], w.BOOL),
        (usb, "WinUsb_Free", [w.HANDLE], w.BOOL),
        (usb, "WinUsb_QueryPipe", [w.HANDLE, c.c_ubyte, c.c_ubyte, c.POINTER(PipeInfo)], w.BOOL),
        (usb, "WinUsb_SetPipePolicy", [w.HANDLE, c.c_ubyte, w.DWORD, w.DWORD, c.c_void_p], w.BOOL),
        (usb, "WinUsb_WritePipe", [w.HANDLE, c.c_ubyte, c.c_void_p, w.ULONG, c.POINTER(w.ULONG), c.c_void_p], w.BOOL),
        (usb, "WinUsb_ReadPipe", [w.HANDLE, c.c_ubyte, c.c_void_p, w.ULONG, c.POINTER(w.ULONG), c.c_void_p], w.BOOL),
    ]
    for dll, name, args, result in definitions:
        function = getattr(dll, name)
        function.argtypes = args
        function.restype = result
    return setup, kernel, usb


SETUP, KERNEL, USB = configure_dlls()
CONFIG = c.WinDLL("cfgmgr32", use_last_error=True)
CONFIG.CM_Get_Parent.argtypes = [c.POINTER(w.DWORD), w.DWORD, w.ULONG]
CONFIG.CM_Get_Parent.restype = w.DWORD
CONFIG.CM_Get_Device_IDW.argtypes = [w.DWORD, w.LPWSTR, w.ULONG, w.ULONG]
CONFIG.CM_Get_Device_IDW.restype = w.DWORD


def check(ok, operation):
    if not ok:
        raise OSError(c.get_last_error(), operation + ": " + c.FormatError(c.get_last_error()))


def device_paths(guid_string="cdb3b5ad-293b-4663-aa36-1aae46463776"):
    import uuid
    guid = GUID.from_buffer_copy(uuid.UUID(guid_string).bytes_le)
    devices = SETUP.SetupDiGetClassDevsW(c.byref(guid), None, None, 0x12)
    if devices == c.c_void_p(-1).value:
        check(False, "SetupDiGetClassDevsW")
    paths = []
    try:
        for index in range(128):
            item = InterfaceData()
            item.size = c.sizeof(item)
            if not SETUP.SetupDiEnumDeviceInterfaces(devices, None, c.byref(guid), index, c.byref(item)):
                if c.get_last_error() == 259:
                    break
                check(False, "SetupDiEnumDeviceInterfaces")
            length = w.DWORD()
            SETUP.SetupDiGetDeviceInterfaceDetailW(devices, c.byref(item), None, 0, c.byref(length), None)
            detail = c.create_string_buffer(length.value)
            c.cast(detail, c.POINTER(w.DWORD))[0] = 8 if c.sizeof(c.c_void_p) == 8 else 6
            device = InterfaceData()  # SP_DEVINFO_DATA has the same field layout.
            device.size = c.sizeof(device)
            check(SETUP.SetupDiGetDeviceInterfaceDetailW(devices, c.byref(item), detail, length, None, c.byref(device)), "interface detail")
            identities = []
            node = device.flags  # DevInst occupies this DWORD in SP_DEVINFO_DATA.
            for _ in range(5):
                identity = c.create_unicode_buffer(512)
                if CONFIG.CM_Get_Device_IDW(node, identity, 512, 0) != 0:
                    break
                identities.append(identity.value)
                parent = w.DWORD()
                if CONFIG.CM_Get_Parent(c.byref(parent), node, 0) != 0:
                    break
                node = parent.value
            paths.append((c.wstring_at(c.addressof(detail) + 4), identities))
    finally:
        SETUP.SetupDiDestroyDeviceInfoList(devices)
    return paths


class Probe:
    def __init__(self, path, packet_size):
        self.packet_size = packet_size
        self.file = KERNEL.CreateFileW(path, 0xC0000000, 3, None, 3, 0x40000000, None)
        if self.file == c.c_void_p(-1).value:
            check(False, "open CMSIS-DAP interface")
        self.handle = w.HANDLE()
        self.connected = False
        try:
            check(USB.WinUsb_Initialize(self.file, c.byref(self.handle)), "WinUsb_Initialize")
            self.pipes = []
            for index in range(16):
                pipe = PipeInfo()
                if not USB.WinUsb_QueryPipe(self.handle, 0, index, c.byref(pipe)):
                    break
                self.pipes.append({"id": pipe.id, "kind": pipe.kind, "packet": pipe.max_packet})
            self.out_pipe = next(p["id"] for p in self.pipes if p["kind"] == 2 and not p["id"] & 0x80)
            self.in_pipe = next(p["id"] for p in self.pipes if p["kind"] == 2 and p["id"] & 0x80)
            timeout = w.ULONG(2000)
            for pipe_id in (self.in_pipe, self.out_pipe):
                check(USB.WinUsb_SetPipePolicy(self.handle, pipe_id, 3, 4, c.byref(timeout)), "set transfer timeout")
        except Exception:
            self.close()
            raise

    def command(self, command):
        data = bytes(command)
        if len(data) > self.packet_size:
            raise ValueError("Command exceeds logical packet size")
        outgoing = c.create_string_buffer(data.ljust(self.packet_size, b"\0"))
        length = w.ULONG()
        check(USB.WinUsb_WritePipe(self.handle, self.out_pipe, outgoing, self.packet_size, c.byref(length), None), "USB write")
        if length.value != self.packet_size:
            raise RuntimeError("Short USB command write")
        incoming = c.create_string_buffer(self.packet_size)
        check(USB.WinUsb_ReadPipe(self.handle, self.in_pipe, incoming, self.packet_size, c.byref(length), None), "USB read")
        response = incoming.raw[:length.value]
        if not response or response[0] != data[0]:
            raise RuntimeError(f"Unexpected response: {response.hex()}")
        return response

    def info(self, item):
        result = self.command([0, item])
        if len(result) < 2 or len(result) < 2 + result[1]:
            raise RuntimeError("Truncated DAP_Info response")
        return result[2:2 + result[1]]

    def transfer(self, request, value=None):
        command = bytes([5, 0, 1, request])
        if value is not None:
            command += struct.pack("<I", value)
        result = self.command(command)
        if len(result) < 3 or result[1:3] != b"\x01\x01":
            raise RuntimeError(f"SWD transfer {request:#x} failed: {result.hex()}")
        if request & 2:
            if len(result) < 7:
                raise RuntimeError("Truncated SWD read")
            return struct.unpack_from("<I", result, 3)[0]

    def read32(self, address):
        self.transfer(0x05, address)  # AP TAR write.
        return self.transfer(0x0F)    # AP DRW read; CMSIS-DAP handles posted reads.

    def close(self):
        if self.handle:
            if self.connected:
                try:
                    self.command([3])
                except Exception:
                    pass
            USB.WinUsb_Free(self.handle)
            self.handle = w.HANDLE()
        if self.file and self.file != c.c_void_p(-1).value:
            KERNEL.CloseHandle(self.file)
            self.file = None
