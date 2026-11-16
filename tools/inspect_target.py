import sys, json, struct, time, hashlib
from pathlib import Path
from winusb_dap import Probe, device_paths
def connect(probe, hz):
    if probe.command([2, 1]) != b'\x02\x01':
        raise RuntimeError('SWD port selection failed')
    probe.connected = True
    for command in (bytes([0x11]) + struct.pack('<I', hz), bytes([4, 0, 100, 0, 0, 0]), bytes([0x13, 0])):
        if probe.command(command)[1] != 0:
            raise RuntimeError('SWD configuration failed')
    sequence = bytes.fromhex('ffffffffffffffff9ee7ffffffffffffffff00')
    if probe.command(bytes([0x12, len(sequence) * 8]) + sequence)[1] != 0:
        raise RuntimeError('SWJ sequence failed')
    dpidr = probe.transfer(2)
    if dpidr in (0, 0xffffffff) or not dpidr & 1:
        raise RuntimeError(f'Invalid DPIDR: {dpidr:#x}')
    probe.transfer(0, 0x1e)
    probe.transfer(8, 0)
    probe.transfer(4, 0x50000000)
    for _ in range(30):
        if probe.transfer(6) & 0xa0000000 == 0xa0000000:
            break
        time.sleep(0.01)
    else:
        raise RuntimeError('Target debug power-up acknowledgement timed out')
    probe.transfer(1, 0x23000052)
    return dpidr


def read_flash(probe, address, size):
    data = bytearray()
    while len(data) < size:
        current = address + len(data)
        words = min(15, (size - len(data)) // 4, (1024 - current % 1024) // 4)
        probe.transfer(5, current)
        reply = probe.command(bytes([6, 0]) + struct.pack('<H', words) + bytes([0x0f]))
        if len(reply) != 4 + 4 * words or int.from_bytes(reply[1:3], 'little') != words or reply[3] != 1:
            raise RuntimeError(f'Flash block read failed at {current:#x}: {reply.hex()}')
        data.extend(reply[4:])
    return bytes(data)




def open_target():
    paths = device_paths()
    if len(paths) != 1:
        raise RuntimeError(f'Expected one probe, found {len(paths)}')
    p = Probe(paths[0][0], 64)
    print('Probe:', [p.info(i).decode(errors='replace') for i in (1,2,3,4)])
    print('DPIDR:', hex(connect(p, 100000)))
    return p

if __name__ == '__main__':
    p = open_target()
    try:
        for a in [0xe000ed00,0xe000edf0,0x40015800,0x1ffff7e0,0x4002201c,0x08000000,0x08000004]:
            try: print(hex(a), hex(p.read32(a)))
            except Exception as e: print(hex(a), str(e))
        data = read_flash(p,0x08000000,64*1024)
        Path('backups').mkdir(exist_ok=True)
        dest = Path('backups/original_flash_64k.bin')
        if dest.exists() and dest.read_bytes() != data:
            raise RuntimeError('Backup already exists and differs; refusing overwrite')
        dest.write_bytes(data)
        print('Backup:',len(data),'SHA256:',hashlib.sha256(data).hexdigest())
    finally:
        p.close()
