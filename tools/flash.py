"""Program GD32E230 main Flash through CMSIS-DAP, preserving untouched pages.

Uses 1 KiB page erase and 32-bit word programming per GD32E23x UM 2.3.
Never writes option bytes, OTP, boot ROM, or the external SPI Flash.
"""
import argparse,hashlib,json,struct,time
from pathlib import Path
from run_ram import open_target,read_flash,write32,halt,regwrite

FMC=0x40022000
def ready(p):
    deadline=time.monotonic()+3
    while True:
        stat=p.read32(FMC+0x0c)
        if not stat&1:
            if stat&0x1c:raise RuntimeError(f'Flash error: {stat:#x}')
            return stat
        if time.monotonic()>deadline:raise TimeoutError('FMC busy')

def program(p,data):
    if not 8<=len(data)<=65536:raise ValueError('Image length out of range')
    sp,pc=struct.unpack_from('<II',data)
    if not 0x20000000<sp<=0x20002000 or not 0x08000000<pc<0x08010000 or not pc&1:
        raise ValueError('Image has invalid vectors')
    halt(p)
    before=read_flash(p,0x08000000,65536)
    Path('backups').mkdir(exist_ok=True)
    tag=time.strftime('%Y%m%d_%H%M%S')
    Path(f'backups/preflash_{tag}.bin').write_bytes(before)
    image=data.ljust((len(data)+1023)&~1023,b'\xff')
    expected=image+before[len(image):]
    write32(p,0xe000e010,0)
    for a in [0xe000e180,0xe000e280]:write32(p,a,0xffffffff)
    regwrite(p,20,1)
    if p.read32(FMC+0x10)&0x80:
        write32(p,FMC+4,0x45670123);write32(p,FMC+4,0xcdef89ab)
    if p.read32(FMC+0x10)&0x80:raise RuntimeError('FMC still locked')
    write32(p,FMC+0x0c,0x3c)
    ready(p)
    write32(p,FMC,p.read32(FMC)&~(1<<15))
    for offset in range(0,len(image),1024):
        address=0x08000000+offset
        write32(p,FMC+0x0c,0x3c)
        write32(p,FMC+0x14,address);write32(p,FMC+0x10,2)
        write32(p,FMC+0x10,0x42);ready(p);write32(p,FMC+0x10,0)
        if read_flash(p,address,1024)!=b'\xff'*1024:raise RuntimeError('Erase verify failed')
        write32(p,FMC+0x10,1)
        for i in range(offset,offset+1024,4):
            word=struct.unpack_from('<I',image,i)[0]
            if word!=0xffffffff:
                write32(p,0x08000000+i,word);ready(p)
        write32(p,FMC+0x10,0)
        if read_flash(p,address,1024)!=image[offset:offset+1024]:raise RuntimeError('Page verify failed')
        print(f'Page {offset//1024}: erased, programmed, verified',flush=True)
    write32(p,FMC+0x10,0x80)
    actual=read_flash(p,0x08000000,65536)
    if actual!=expected:raise RuntimeError('Full Flash verification failed')
    report={'image_bytes':len(data),'erased_pages':len(image)//1024,
        'image_sha256':hashlib.sha256(data).hexdigest(),
        'full_flash_sha256':hashlib.sha256(actual).hexdigest(),'verify':'PASS',
        'untouched_pages_preserved':True,'option_bytes_written':False}
    Path('build/flash_report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)
    write32(p,0xe000edfc,0);write32(p,0xe000ed08,0x08000000)
    write32(p,0xe000ed0c,0x05fa0004)
    write32(p,0xe000edf0,0xa05f0001)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image',help='Explicit standalone Flash image; never use an SRAM/factory-driver image')
    args=ap.parse_args()
    p=open_target()
    try:
        program(p,Path(args.image).read_bytes())
        for i in range(15):
            time.sleep(1)
            state=p.read32(0x20001e00);row=p.read32(0x20001e04)
            print('Runtime:',hex(state),'rows:',row,flush=True)
            if state==0x50415353:break
    finally:
        p.connected=False;p.close()
