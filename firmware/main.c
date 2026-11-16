#include <stdint.h>
#define REG(a) (*(volatile uint32_t *)(a))
#define PA 0x48000000u
#define PB 0x48000400u
#define PF 0x48001400u
#define STATUS REG(0x20001e00)
static void high(uint32_t port, unsigned pin) { REG(port+0x18)=1u<<pin; }
static void low(uint32_t port, unsigned pin) { REG(port+0x28)=1u<<pin; }
#ifndef FACTORY_DRIVER
static void output(uint32_t port, unsigned pin) {
    REG(port)=(REG(port)&~(3u<<(pin*2)))|(1u<<(pin*2));
    REG(port+4)&=~(1u<<pin);
    REG(port+8)=(REG(port+8)&~(3u<<(pin*2)))|(1u<<(pin*2));
    REG(port+12)&=~(3u<<(pin*2));
}
#endif
static void delay_ms(unsigned ms) {
    // Reset clock is IRC8M. SysTick uses the processor clock.
    REG(0xe000e010)=0; REG(0xe000e014)=7999;
#ifdef FACTORY_DRIVER
    REG(0xe000e014)=71999;
#endif
    REG(0xe000e018)=0;
    REG(0xe000e010)=5;
    while(ms--) while(!(REG(0xe000e010)&(1u<<16))) {}
    REG(0xe000e010)=0;
}
static void byte(unsigned b) {
#if defined(PARALLEL_DRIVER)
    REG(PA+0x18)=((~b&255u)<<16)|(b&255u);
    low(PF,6); high(PF,6);
#elif defined(FACTORY_DRIVER)
    ((void (*)(unsigned))0x08001851)(b);
#else
    for(unsigned i=0;i<8;i++) {
        if(b&0x80) high(PB,5); else low(PB,5);
        low(PB,3); high(PB,3); b<<=1;
    }
    high(PB,3);
#endif
}
static void cmd(unsigned c) {
#ifdef FACTORY_DRIVER
    ((void (*)(unsigned))0x08001825)(c);
#else
    low(PB,4); byte(c); high(PB,4);
#endif
}
static void config(unsigned c, const uint8_t *p, unsigned n) {
    cmd(c); while(n--) byte(*p++);
}
#define CFG(c, ...) do { static const uint8_t v[]={__VA_ARGS__}; config(c,v,sizeof(v)); } while(0)
static uint16_t rgb(unsigned r,unsigned g,unsigned b) {
    return ((r>>3)<<11)|((g>>2)<<5)|(b>>3);
}
static void init(void) {
#ifndef FACTORY_DRIVER
    REG(0x40021014)|=(1u<<17)|(1u<<18)|(1u<<22);
    (void)REG(0x40021014);
    low(PA,11); high(PA,12); high(PA,15);
    high(PB,3); high(PB,4); low(PB,5);
    low(PF,6); high(PF,7);
    output(PA,11); output(PA,12); output(PA,15);
    output(PB,3); output(PB,4); output(PB,5);
    output(PF,6); output(PF,7);
#ifdef PARALLEL_DRIVER
    for(unsigned pin=0;pin<8;pin++) output(PA,pin);
    high(PF,6); high(PF,7);
#endif
#endif
    delay_ms(20); low(PA,15);
    high(PA,12); delay_ms(10); low(PA,12); delay_ms(10);
    high(PA,12); delay_ms(120);
    cmd(0x11); delay_ms(120);
    // Panel-specific parameters recovered from the backed-up factory program.
    CFG(0xb2,0x0c,0x0c,0x00,0x33,0x33);
    CFG(0x36,0x00); CFG(0x3a,0x55);
    CFG(0xb7,0x35); CFG(0xbb,0x3a); CFG(0xc0,0x2c);
    CFG(0xc2,0x01); CFG(0xc3,0x1d); CFG(0xc4,0x20); CFG(0xc6,0x0f);
    CFG(0xd0,0xa4,0xa1); CFG(0xd6,0xa1);
    CFG(0xe0,0xf0,0x05,0x0c,0x0b,0x0a,0x17,0x2c,0x44,0x43,0x36,0x11,0x10,0x28,0x30);
    CFG(0xe1,0xf0,0x06,0x09,0x08,0x07,0x03,0x2c,0x33,0x43,0x38,0x15,0x16,0x2e,0x36);
    cmd(0x21); cmd(0x13); cmd(0x29); delay_ms(20);
}
static void pattern(void) {
    static const uint16_t bars[]={0xffff,0xffe0,0x07ff,0x07e0,0xf81f,0xf800,0x001f,0x0000};
    CFG(0x2a,0,0,0,239); CFG(0x2b,0,0,0,239); cmd(0x2c);
    for(unsigned y=0;y<240;y++) {
        for(unsigned x=0;x<240;x++) {
            uint16_t c;
            if(y<144) c=bars[x/30];
            else if(y<176) { unsigned g=(x/15)*17; c=rgb(g,g,g); }
            else if(y<224) {
                unsigned g=x*255/239;
                c=y<192?rgb(g,0,0):y<208?rgb(0,g,0):rgb(0,0,g);
            } else c=((x/8+(y-224)/8)&1)?0xffff:0;
            if(x==0||x==239||y==0||y==239) c=0xffff;
            byte(c>>8); byte(c&255);
        }
        REG(0x20001e04)=y+1;
    }
    high(PA,15); high(PA,11);
}
void Reset_Handler(void) {
    __asm volatile("cpsid i");
    STATUS=0x53544152; REG(0x20001e04)=0;
    REG(0xe000e010)=0;
    init();
    STATUS=0x494e4954;
    pattern(); STATUS=0x50415353;
    while(1) __asm volatile("nop");
}
void Default_Handler(void) { STATUS=0x4641554c; while(1) {} }
__attribute__((section(".isr_vector"),used))
const uintptr_t vectors[48]={ [0]=0x20002000,[1]=(uintptr_t)Reset_Handler,
    [2]=(uintptr_t)Default_Handler,[3]=(uintptr_t)Default_Handler };
