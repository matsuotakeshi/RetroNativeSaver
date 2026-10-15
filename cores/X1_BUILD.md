# X1 two-drive build for RetroNativeSaver

Based on https://github.com/libretro/xmil-libretro
Commit: 3106aa54ffb244cca4019a6e95dacaa698781bc3

Changes: libretro/libretro.c reads a generated M3U with one or two absolute paths;
libretro/xmil.c inserts the second path into floppy drive index 1 after machine initialization.
The regular single-image loading path is retained.

Windows x64 binary built with MSYS2 UCRT64 GCC, with static compiler runtimes:

    cd libretro
    make -j4 platform=win CC=gcc CXX=g++

The modified complete source (excluding build artifacts) is in
`third_party/xmil-two-drive-source.zip` in the source distribution.
Upstream licensing and notices are included there; see also X1_LICENSE.txt.
This build is separate from the installed RetroArch x1_libretro.dll.

The Git repository does not include the compiled DLL. Extract the source ZIP,
run the command above in its `libretro` directory, and copy the generated DLL
to this project's `cores/x1_rns_libretro.dll` before running `build.bat`.
Generated FNT*.TMP files and prebuilt legacy GBA toolchain binaries are omitted
from the source ZIP; they are not required by the Windows libretro build.
