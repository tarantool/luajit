# This module exposes following variables to the project:
# * BUILDVM_MODE
# * TARGET_C_FLAGS
# * TARGET_VM_FLAGS
# * TARGET_BIN_FLAGS
# * TARGET_SHARED_FLAGS
# * TARGET_LIBS

if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
  set(BUILDVM_MODE machasm)
else() # Linux and FreeBSD.
  set(BUILDVM_MODE elfasm)
endif()

LuaJITTestArch(TESTARCH "${TARGET_C_FLAGS}")
LuaJITArch(LUAJIT_ARCH "${TESTARCH}")

# Target-specific compiler options.
#
# x86/x64 only: For GCC 4.2 or higher and if you don't intend to
# distribute the binaries to a different machine you could also
# use: -march=native.
if(LUAJIT_ARCH STREQUAL "x86")
  AppendFlags(TARGET_C_FLAGS -march=i686 -msse -msse2 -mfpmath=sse -fno-omit-frame-pointer)
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
  if(LUAJIT_ARCH STREQUAL "x64")
    # XXX: Set -pagezero_size to hint <mmap> when allocating 32
    # bit memory on OSX/x64, otherwise the lower 4GB are blocked.
    AppendFlags(TARGET_BIN_FLAGS -pagezero_size 10000 -image_base 100000000)
    AppendFlags(TARGET_SHARED_FLAGS -image_base 7fff04c4a000)
  endif()
  AppendFlags(TARGET_SHARED_FLAGS -single_module -undefined dynamic_lookup)
else() # Linux and FreeBSD.
  AppendFlags(TARGET_BIN_FLAGS -Wl,-E)
  list(APPEND TARGET_LIBS dl)
endif()

# Auxiliary flags for the VM core.
# XXX: ASAN-related build flags are stored in CMAKE_C_FLAGS.
set(TARGET_VM_FLAGS "${CMAKE_C_FLAGS} ${TARGET_C_FLAGS}")

unset(LUAJIT_ARCH)
unset(TESTARCH)
