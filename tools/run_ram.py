import argparse,struct,time,hashlib
from pathlib import Path
from inspect_target import open_target,read_flash

def write32(p,a,v):
    p.transfer(5,a);p.transfer(13,v)

def write_block(p,a,data):
    data=data.ljust((len(data)+3)&~3,b'\0')
    for i in range(0,len(data),4):write32(p,a+i,struct.unpack_from('<I',data,i)[0])

def halt(p):
    write32(p,0xe000edf0,0xa05f0003)
    for _ in range(100):
        if p.read32(0xe000edf0)&(1<<17):return
        time.sleep(.01)
    raise RuntimeError('Core did not halt')

def regwrite(p,r,v):
    write32(p,0xe000edf8,v);write32(p,0xe000edf4,0x10000|r)
    if not p.read32(0xe000edf0)&(1<<16):raise RuntimeError('Register transfer failed')

def regread(p,r):
    write32(p,0xe000edf4,r)
    return p.read32(0xe000edf8)

def launch(p,data,base=0x20000000):
    halt(p);write32(p,0xe000e010,0)
    for a in [0xe000e180,0xe000e280]:write32(p,a,0xffffffff)
    write_block(p,base,data)
    if read_flash(p,base,(len(data)+3)&~3)[:len(data)]!=data:raise RuntimeError('RAM verify failed')
    sp,pc=struct.unpack_from('<II',data)
    write32(p,0xe000ed08,base)
    regwrite(p,17,sp);regwrite(p,20,1);regwrite(p,16,0x01000000);regwrite(p,15,pc)
    write32(p,0xe000edf0,0xa05f0001)

FACTORY_SHA256='5795f431cf1166aabec2453eb476a25913d5f968b5adb61d4613200c1086ceb8'

def reset_and_halt(p):
    halt(p)
    write32(p,0xe000edfc,1)
    write32(p,0xe000ed0c,0x05fa0004)
    time.sleep(.1)
    halt(p)
    write32(p,0xe000edfc,0)

def prepare_factory(p):
    original=read_flash(p,0x08000000,65536)
    if hashlib.sha256(original).hexdigest()!=FACTORY_SHA256:
        raise RuntimeError('Factory firmware differs: absolute ROM function addresses are not safe to call')
    # Let the matching original firmware establish its PLL, GPIO and SPI configuration.
    reset_and_halt(p)
    write32(p,0xe000edf0,0xa05f0001)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        time.sleep(.1)
        if p.read32(0x40013000)==0xc34e and p.read32(0x48000014)&0x800:
            halt(p)
            return
    raise RuntimeError('Factory SPI/backlight initialization did not become ready')

if __name__=='__main__':
    ap=argparse.ArgumentParser(description='Run the color test in SRAM without programming Flash.')
    ap.add_argument('--driver',choices=['factory','software','parallel'],default='factory')
    ap.add_argument('--image',type=Path,help='Override image; its vector table must match the driver load address')
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    images={'factory':('build/factory_driver.bin',0x20001000),
            'software':('build/colorbars_ram.bin',0x20000000),
            'parallel':('build/parallel_driver.bin',0x20000000)}
    name,base=images[args.driver]
    image=args.image or root/name
    data=image.read_bytes()
    if not 8<=len(data)<=0x1c00-(base-0x20000000):
        raise ValueError('Image overlaps the reserved status/stack area')
    p=open_target()
    try:
        if (p.read32(0xe000ed00)>>4)&0xfff!=0xd20:
            raise RuntimeError('Expected a Cortex-M23 target')
        if args.driver=='factory':prepare_factory(p)
        else:reset_and_halt(p)
        launch(p,data,base)
        for i in range(20):
            time.sleep(1)
            state=p.read32(0x20001e00);row=p.read32(0x20001e04)
            print('state',hex(state),'rows',row,flush=True)
            if state==0x50415353:break
        else:
            halt(p)
            print('PC',hex(regread(p,15)),'xPSR',hex(regread(p,16)))
            raise RuntimeError('Rendering did not finish')
    finally:
        p.connected=False
        p.close()
