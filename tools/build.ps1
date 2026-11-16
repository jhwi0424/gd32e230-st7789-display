param([string]$ToolchainBin = $env:ARM_GCC_BIN)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
if (-not $ToolchainBin) {
    $Gcc=Get-Command arm-none-eabi-gcc.exe -ErrorAction SilentlyContinue
    if ($Gcc) { $ToolchainBin=Split-Path $Gcc.Source }
}
if (-not $ToolchainBin) {
    $Candidate=Get-ChildItem 'C:\ST\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins' -Directory -Filter '*externaltools.gnu-tools-for-stm32*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    if ($Candidate) { $ToolchainBin=Join-Path $Candidate.FullName 'tools\bin' }
}
if (-not $ToolchainBin) { throw 'Set ARM_GCC_BIN or pass -ToolchainBin to select Arm GNU tools.' }
$Bin=$ToolchainBin
New-Item -ItemType Directory -Force build | Out-Null
$Variants=@(
    @{Name='factory_driver';Base='0x20001000';Define='FACTORY_DRIVER'},
    @{Name='colorbars_ram';Base='0x20000000';Define=''},
    @{Name='colorbars_flash';Base='0x08000000';Define=''},
    @{Name='parallel_driver';Base='0x20000000';Define='PARALLEL_DRIVER'}
)
foreach ($Variant in $Variants) {
    $Name=$Variant.Name; $Base=$Variant.Base
    $ArgsList=@('-mcpu=cortex-m23','-mthumb','-Os','-ffreestanding','-fno-builtin','-nostdlib','-Wall','-Wextra','-Werror',"-Wl,--defsym=CODE_BASE=$Base",'-Wl,--build-id=none',"-Wl,-Map=build/$Name.map",'-T','firmware/link.ld','firmware/main.c','-o',"build/$Name.elf")
    if ($Variant.Define) { $ArgsList+="-D$($Variant.Define)" }
    & "$Bin\arm-none-eabi-gcc.exe" @ArgsList
    if($LASTEXITCODE -ne 0){throw 'Compilation failed'}
    & "$Bin\arm-none-eabi-objcopy.exe" -O binary "build/$Name.elf" "build/$Name.bin"
    if($LASTEXITCODE -ne 0){throw 'Binary export failed'}
    & "$Bin\arm-none-eabi-size.exe" "build/$Name.elf"
    if($LASTEXITCODE -ne 0){throw 'Size inspection failed'}
}
