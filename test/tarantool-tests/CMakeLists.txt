# Test suite that has been moved from Tarantool repository in
# scope of https://github.com/tarantool/tarantool/issues/4478.

# See the rationale in the root CMakeLists.txt.
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

find_program(PROVE prove)
if(NOT PROVE)
  message(WARNING "`prove' is not found, so tarantool-tests target is not generated")
  return()
endif()

macro(BuildTestCLib lib sources)
  add_library(${lib} SHARED EXCLUDE_FROM_ALL ${sources})
  target_include_directories(${lib} PRIVATE
    ${LUAJIT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
  )
  set_target_properties(${lib} PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
    PREFIX ""
  )

  # XXX: This change affects the current cmake variable scope and
  # so a user should care to don't use it in a top level scope.
  # The dynamic libraries are loaded with LuaJIT binary and use
  # symbols from it. So it is totally OK to have unresolved
  # symbols at build time.
  if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
    set_target_properties(${lib} PROPERTIES
      LINK_FLAGS "-undefined dynamic_lookup"
    )
  else()
    # FIXME: Unfortunately, there is no another way to suppress
    # this linker option, so just strip it out from the flags.
    string(REPLACE "-Wl,--no-undefined" ""
      CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS}"
    )
  endif()
  # XXX: Append the lib to be built to the dependency list.
  # Unfortunately, there is no convenient way in CMake to extend
  # the list in parent scope other than join two strings with
  # semicolon. If one finds the normal way to make it work, feel
  # free to reach me.
  set(TESTLIBS "${lib};${TESTLIBS}" PARENT_SCOPE)
  # Add the directory where the lib is built to the LUA_CPATH
  # environment variable, so LuaJIT can find and load it.
  # XXX: Here we see the other side of the coin. If one joins two
  # strings with semicolon, the value automatically becomes a
  # list. I found a single working solution to make LUA_CPATH be
  # a string via "escaping" the semicolon right in string
  # interpolation.
  set(LUA_CPATH "${CMAKE_CURRENT_BINARY_DIR}/?${CMAKE_SHARED_LIBRARY_SUFFIX}\;${LUA_CPATH}" PARENT_SCOPE)
  # Also add this directory to LD_LIBRARY_PATH environment
  # variable, so FFI machinery can find and load it.
  set(LD_LIBRARY_PATH "${CMAKE_CURRENT_BINARY_DIR}:${LD_LIBRARY_PATH}" PARENT_SCOPE)
endmacro()

add_subdirectory(gh-4427-ffi-sandwich)
add_subdirectory(gh-5813-resolving-of-c-symbols/both)
add_subdirectory(gh-5813-resolving-of-c-symbols/hash)
add_subdirectory(gh-5813-resolving-of-c-symbols/gnuhash)
add_subdirectory(gh-5813-resolving-of-c-symbols/stripped)
add_subdirectory(gh-6098-fix-side-exit-patching-on-arm64)
add_subdirectory(gh-6189-cur_L)
add_subdirectory(lj-49-bad-lightuserdata)
add_subdirectory(lj-601-fix-gc-finderrfunc)
add_subdirectory(lj-flush-on-trace)
add_subdirectory(misclib-getmetrics-capi)
add_subdirectory(misclib-sysprof-capi)

# The part of the memory profiler toolchain is located in tools
# directory, jit, profiler, and bytecode toolchains are located
# in src/ directory and auxiliary tests-related modules are
# located in the current directory (but tests are run in the
# binary directory), so LUA_PATH need to be updated.
set(LUA_PATH
  "${CMAKE_CURRENT_SOURCE_DIR}/?.lua\;${PROJECT_SOURCE_DIR}/tools/?.lua\;${PROJECT_SOURCE_DIR}/src/?.lua"
)
set(LUA_TEST_SUFFIX .test.lua)
set(LUA_TEST_FLAGS --failures --shuffle)
set(LUA_TEST_ENV
  "LUA_PATH=\"${LUA_PATH}\;\;\""
  "LUA_CPATH=\"${LUA_CPATH}\;\;\""
)

if(CMAKE_VERBOSE_MAKEFILE)
  list(APPEND LUA_TEST_FLAGS --verbose)
endif()

# XXX: Since the auxiliary libraries are built as a dynamically
# loaded modules on MacOS instead of shared libraries as it is
# done on Linux and BSD, another environment variable should be
# used to guide <ffi.load> while searching the extension.
if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
  # XXX: Apple tries their best to "protect their users from
  # malware". As a result SIP (see the link[1] below) has been
  # designed and released. Now, Apple developers are so protected,
  # that they can load nothing being not installed in the system,
  # since some programs sanitize the environment before they start
  # child processes. Specifically, environment variables starting
  # with DYLD_ and LD_ are unset for child process started by
  # system programs (like /usr/bin/env used for preparing testing
  # environment). For more info, see the docs[2] below.
  #
  # These environment variables are used by FFI machinery to find
  # the proper shared library, hence we can still tweak testing
  # environment before calling <ffi.load>. However, the value
  # can't be passed via the standard environment variable, so we
  # prepend TEST_ prefix to its name to get around SIP magic
  # tricks. Finally, to set the variable required by FFI machinery
  # the introduced <utils.tweakenv> routine is used.
  #
  # [1]: https://support.apple.com/en-us/HT204899
  # [2]: https://developer.apple.com/library/archive/documentation/Security/Conceptual/System_Integrity_Protection_Guide/RuntimeProtections/RuntimeProtections.html
  list(APPEND LUA_TEST_ENV TEST_DYLD_LIBRARY_PATH="${LD_LIBRARY_PATH}")
else()
  list(APPEND LUA_TEST_ENV LD_LIBRARY_PATH="${LD_LIBRARY_PATH}")
endif()

# LUA_CPATH and LD_LIBRARY_PATH variables and also TESTLIBS list
# with dependecies are set in scope of BuildTestLib macro.
add_custom_target(tarantool-tests
  DEPENDS ${LUAJIT_TEST_BINARY} ${TESTLIBS}
)
add_custom_command(TARGET tarantool-tests
  COMMENT "Running Tarantool tests"
  COMMAND
  env
    ${LUA_TEST_ENV}
    ${PROVE} ${CMAKE_CURRENT_SOURCE_DIR}
      --exec '${LUAJIT_TEST_COMMAND}'
      --ext ${LUA_TEST_SUFFIX}
      ${LUA_TEST_FLAGS}
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

