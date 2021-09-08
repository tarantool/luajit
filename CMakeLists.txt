# LuaJIT -- interpreter and JIT compiler for Lua language.
# This is the main entry point for building, testing and
# packaging the project.
# Major portions taken verbatim or adapted from the uJIT.
# Copyright (C) 2020-2021 LuaVela Authors.
# Copyright (C) 2015-2020 IPONWEB Ltd.

# --- Initial setup ------------------------------------------------------------

# See the rationale below (near LUAJIT_TEST_BINARY variable).
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)
project(LuaJIT C)

# XXX: Originally CMake machinery is introduced to make LuaJIT
# testing self-sufficient. Since there are only few systems
# covered by the tests in our CI, there is no need to support
# others for now and the original build system can be used.
if(NOT(
   CMAKE_SYSTEM_NAME STREQUAL "Linux" OR
   CMAKE_SYSTEM_NAME STREQUAL "Darwin" OR
   CMAKE_SYSTEM_NAME STREQUAL "FreeBSD"
))
  message(FATAL_ERROR
    "Please use the old build system:\n\tmake -f Makefile.original <options>"
  )
endif()

# --- Fine-tuning cmake environment --------------------------------------------

set(CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

include(LuaJITUtils)
include(SetVersion)

# --- Variables to be exported to child scopes ---------------------------------

SetVersion(
  LUAJIT_VERSION
  LUAJIT_VERSION_MAJOR
  LUAJIT_VERSION_MINOR
  LUAJIT_VERSION_PATCH
  LUAJIT_VERSION_TWEAK
  LUAJIT_PRERELEASE
)

set(LUAJIT_SOURCE_DIR "${PROJECT_SOURCE_DIR}/src")
set(LUAJIT_BINARY_DIR "${PROJECT_BINARY_DIR}/src")

# Names of the CLI binaries.
set(LUAJIT_CLI_NAME "luajit")
set(LUAJIT_LIB_NAME "luajit")

# Specialized install paths.
set(LUAJIT_DATAROOTDIR
  share/luajit-${LUAJIT_VERSION_MAJOR}.${LUAJIT_VERSION_MINOR}.${LUAJIT_VERSION_PATCH}${LUAJIT_PRERELEASE}
)
set(LUAJIT_INCLUDEDIR
  include/luajit-${LUAJIT_VERSION_MAJOR}.${LUAJIT_VERSION_MINOR}
)

# Mixed mode creates a static + dynamic library and a statically
# linked luajit. Static mode creates a static library and a
# statically linked luajit. Dynamic mode creates a dynamic library
# and a dynamically linked luajit.
# XXX: dynamically linked executable will only run when the
# library is installed!
set(BUILDMODE_VALUES mixed static dynamic)
# The default build mode is mixed mode on POSIX.
list(GET BUILDMODE_VALUES 0 BUILDMODE_DEFAULT)
set(BUILDMODE ${BUILDMODE_DEFAULT} CACHE STRING
  "Build mode. Choose one of the following: ${BUILDMODE_VALUES}."
)
set_property(CACHE BUILDMODE PROPERTY STRINGS ${BUILDMODE_VALUES})

# Check that BUILDMODE value is correct.
# FIXME: In CMake 3.5 we'll be able to use IN_LIST here.
list(FIND BUILDMODE_VALUES ${BUILDMODE} BUILDMODE_INDEX)
if(BUILDMODE_INDEX EQUAL -1)
  message(FATAL_ERROR "BUILDMODE must be one of the following: ${BUILDMODE_VALUES}.")
endif()

# --- Compilation flags setup --------------------------------------------------

if(NOT CMAKE_INSTALL_PREFIX STREQUAL "/usr/local")
  AppendFlags(TARGET_C_FLAGS -DLUA_ROOT='"${CMAKE_INSTALL_PREFIX}"')
endif()

if(CMAKE_LIBRARY_ARCHITECTURE)
  AppendFlags(TARGET_C_FLAGS -DLUA_MULTILIB='"lib/${CMAKE_LIBRARY_ARCHITECTURE}"')
endif()

# Since the assembler part does NOT maintain a frame pointer, it's
# pointless to slow down the C part by not omitting it. Debugging,
# tracebacks and unwinding are not affected -- the assembler part
# has frame unwind information and GCC emits it where needed (x64)
# or with -g.
AppendFlags(CMAKE_C_FLAGS -fomit-frame-pointer -fno-stack-protector)

# Redefined to benefit from expanding macros in gdb.
set(CMAKE_C_FLAGS_DEBUG "-g -ggdb3")
set(CMAKE_C_FLAGS_RELWITHDEBINFO "-O2 -DNDEBUG -g -ggdb3")
# Redefined since default cmake release optimization level is O3.
set(CMAKE_C_FLAGS_RELEASE "-O2 -DNDEBUG")

AppendFlags(CMAKE_C_FLAGS -Wall)
option(LUAJIT_ENABLE_WARNINGS "Build LuaJIT with warnings enabled" OFF)
if(LUAJIT_ENABLE_WARNINGS)
  AppendFlags(CMAKE_C_FLAGS
    -Wextra
    -Wdeclaration-after-statement
    -Wpointer-arith
    -Wredundant-decls
    -Wshadow
  )
endif()

# Auxiliary flags for main targets (libraries, binaries).
AppendFlags(TARGET_C_FLAGS
  -D_FILE_OFFSET_BITS=64
  -D_LARGEFILE_SOURCE
  -U_FORTIFY_SOURCE
)

# Permanently disable the FFI extension to reduce the size of the
# LuaJIT executable. But please consider that the FFI library is
# compiled-in, but NOT loaded by default. It only allocates any
# memory, if you actually make use of it.
option(LUAJIT_DISABLE_FFI "FFI support" OFF)
if(LUAJIT_DISABLE_FFI)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_DISABLE_FFI)
endif()

# Features from Lua 5.2 that are unlikely to break existing code
# are enabled by default. Some other features that *might* break
# some existing code (e.g. __pairs or os.execute() return values)
# can be enabled here.
# XXX: this does not provide full compatibility with Lua 5.2 at
# this time.
option(LUAJIT_ENABLE_LUA52COMPAT "Compatibility with Lua 5.2" OFF)
if(LUAJIT_ENABLE_LUA52COMPAT)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_ENABLE_LUA52COMPAT)
endif()

# Disable the JIT compiler, i.e. turn LuaJIT into a pure
# interpreter.
option(LUAJIT_DISABLE_JIT "JIT support" OFF)
if(LUAJIT_DISABLE_JIT)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_DISABLE_JIT)
endif()

# Some architectures (e.g. PPC) can use either single-number (1)
# or dual-number (2) mode. Please see LJ_ARCH_NUMMODE in lj_arch.h
# for details.
set(LUAJIT_NUMMODE_VALUES 1 2)
set(LUAJIT_NUMMODE_DEFAULT "")
set(LUAJIT_NUMMODE ${LUAJIT_NUMMODE_DEFAULT} CACHE STRING
  "Switch to single-number or dual-number mode."
)
# XXX: explicitly added empty string allows to disable this flag
# in GUI.
set_property(CACHE LUAJIT_NUMMODE PROPERTY STRINGS
  ${LUAJIT_NUMMODE_DEFAULT} ${LUAJIT_NUMMODE_VALUES}
)

if(NOT LUAJIT_NUMMODE STREQUAL LUAJIT_NUMMODE_DEFAULT)
  # Check that LUAJIT_NUMMODE value is correct.
  # FIXME: In CMake 3.5 we'll be able to use IN_LIST here.
  list(FIND LUAJIT_NUMMODE_VALUES ${LUAJIT_NUMMODE} LUAJIT_NUMMODE_INDEX)
  if(LUAJIT_NUMMODE_INDEX EQUAL -1)
    message(FATAL_ERROR "LUAJIT_NUMMODE must be '1' for single-number mode or '2' for dual-number mode.")
  endif()
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_NUMMODE=${LUAJIT_NUMMODE})
endif()

# Enable GC64 mode for x64.
option(LUAJIT_ENABLE_GC64 "GC64 mode for x64" OFF)
if(LUAJIT_ENABLE_GC64)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_ENABLE_GC64)
endif()

# Disable memory profiler.
option(LUAJIT_DISABLE_MEMPROF "LuaJIT memory profiler support" OFF)
if(LUAJIT_DISABLE_MEMPROF)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_DISABLE_MEMPROF)
endif()

# Disable platform and Lua profiler.
option(LUAJIT_DISABLE_SYSPROF "LuaJIT platform and Lua profiler support" OFF)
if(LUAJIT_DISABLE_SYSPROF)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_DISABLE_SYSPROF)
endif()

# Switch to harder (and slower) hash function when a collision
# chain in the string hash table exceeds a certain length.
option(LUAJIT_SMART_STRINGS "Harder string hashing function" ON)
if(LUAJIT_SMART_STRINGS)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_SMART_STRINGS=1)
endif()

# XXX: Note that most of the options below are NOT suitable for
# benchmarking or release mode!

# Use the system provided memory allocator (realloc) instead of
# the bundled memory allocator. This is slower, but sometimes
# helpful for debugging. This option cannot be enabled on x64
# without GC64, since realloc usually doesn't return addresses in
# the right address range. OTOH this option is mandatory for
# Valgrind's memcheck tool on x64 and the only way to get useful
# results from it for all other architectures.
option(LUAJIT_USE_SYSMALLOC "System provided memory allocator (realloc)" OFF)
if(LUAJIT_USE_SYSMALLOC)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_USE_SYSMALLOC)
endif()

# This define is required to run LuaJIT under Valgrind. The
# Valgrind header files must be installed. You should enable debug
# information, too. Use --suppressions=lj.supp to avoid some false
# positives.
option(LUAJIT_USE_VALGRIND "Valgrind support" OFF)
if(LUAJIT_USE_VALGRIND)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_USE_VALGRIND)
endif()

# This is the client for the GDB JIT API. GDB 7.0 or higher is
# required to make use of it. See lj_gdbjit.c for details.
# Enabling this causes a non-negligible overhead, even when not
# running under GDB.
option(LUAJIT_USE_GDBJIT "GDB JIT support" OFF)
if(LUAJIT_USE_GDBJIT)
  AppendFlags(TARGET_C_FLAGS -DLUAJIT_USE_GDBJIT)
endif()

# Turn on assertions for the Lua/C API to debug problems with
# lua_* calls. This is rather slow -- use only while developing C
# libraries/embeddings.
option(LUA_USE_APICHECK "Assertions for the Lua/C API" OFF)
if(LUA_USE_APICHECK)
  AppendFlags(TARGET_C_FLAGS -DLUA_USE_APICHECK)
endif()

# Turn on assertions for the whole LuaJIT VM. This significantly
# slows down everything. Use only if you suspect a problem with
# LuaJIT itself.
option(LUA_USE_ASSERT "Assertions for the whole LuaJIT VM" OFF)
if(LUA_USE_ASSERT)
  AppendFlags(TARGET_C_FLAGS -DLUA_USE_ASSERT)
endif()

# TODO: Implement a configuration option to enable ASAN.
# There are two entries of LUAJIT_USE_ASAN define:
# $ grep -rnF 'LUAJIT_USE_ASAN' .
# ./src/lj_str.c:15:#if LUAJIT_USE_ASAN
# ./src/host/buildvm.c:36:#if LUAJIT_USE_ASAN
# At the same time this flag is not provided by LuaJIT original
# build system (i.e. src/Makefile.original) so there are no
# related compiler and linker flags passed. This should be done
# the right way later.

# --- Main source tree ---------------------------------------------------------

add_subdirectory(src)

# --- Auxiliary files ----------------------------------------------------------

add_subdirectory(etc)

# --- Tools --------------------------------------------------------------------

add_subdirectory(tools)

# --- Testing source tree ------------------------------------------------------

# Auxiliary options for testing.

# FIXME: There might be a parent project integrating LuaJIT
# sources in its source tree as a third party library
# (e.g. https://github.com/tarantool/tarantool), so <test> target
# can be already reserved there. This option allows to omit <test>
# target configuration for LuaJIT to respect CMP0002 policy.
option(LUAJIT_USE_TEST "Generate <test> target" ON)

# FIXME: If LuaJIT is used in parent project, provide an option
# to choose which binary to be used for running LuaJIT tests.
# XXX: This variable is used as a dependency for tests, and its
# default value is $<TARGET_FILE:${LUAJIT_DEPS}> assigned in <src>
# directory CMakeLists. Unfortunately CMake fails with generator
# expressions expansions used in <add_custom_(command|target)>.
# As a result the minimal required CMake version is set to 3.1.
# For more info, see CMake Release notes for 3.1 version.
# https://cmake.org/cmake/help/latest/release/3.1.html#commands
# XXX: This option is moved below source tree processing since
# the default binary target need to be generated.
set(LUAJIT_TEST_BINARY ${LUAJIT_BINARY} CACHE STRING
  "Lua implementation to be used for tests. Default is 'luajit'."
)

# FIXME: If LuaJIT is used in parent project, provide an option
# to pass Lua code to be run before tests are started.
# XXX: Attentive reader might point to LUA_INIT environment
# variable, but this is less secure way to run the particular Lua
# code. As a result the application to be run against LuaJIT test
# can ignore it (for more info, see the following issue).
# https://github.com/tarantool/tarantool/issues/5744
# XXX: This variable is used as '-e' Lua runtime flag value and
# the hack works since the code passed via '-e' is executed before
# the code passed via Lua script, *but* both are executed in a
# single environment. Hence, if this environment need to be
# tweaked, the introduced option can be used.
# The default behaviour is defined in test/luajit-test-init.lua.
set(LUAJIT_TEST_INIT "${PROJECT_SOURCE_DIR}/test/luajit-test-init.lua" CACHE STRING
  "Lua code need to be run before tests are started."
)

add_subdirectory(test)

# --- Misc rules ---------------------------------------------------------------

# XXX: Implement <uninstall> target using the following recipe:
# https://gitlab.kitware.com/cmake/community/-/wikis/FAQ#can-i-do-make-uninstall-with-cmake
if(NOT TARGET uninstall)
  configure_file(${CMAKE_MODULE_PATH}/cmake_uninstall.cmake.in
    cmake_uninstall.cmake @ONLY ESCAPE_QUOTES)

  add_custom_target(uninstall
    COMMAND ${CMAKE_COMMAND} -P ${CMAKE_CURRENT_BINARY_DIR}/cmake_uninstall.cmake
  )
endif()
