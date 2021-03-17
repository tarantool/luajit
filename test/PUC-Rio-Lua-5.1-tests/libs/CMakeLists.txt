# Test suite that has been added from PUC-Rio Lua 5.1 test archive
# in scope of https://github.com/tarantool/tarantool/issues/5845.

# See the rationale in the root CMakeLists.txt.
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

# Build additional C libraries for tests.
macro(BuildTestCLib lib sources)
  add_library(${lib} SHARED EXCLUDE_FROM_ALL ${sources})
  target_include_directories(${lib} PRIVATE
    ${LUAJIT_SOURCE_DIR}
  )
  set_target_properties(${lib} PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
    PREFIX ""
  )
  # XXX: The dynamic libraries are loaded with LuaJIT binary and
  # use symbols from it. So it is totally OK to have unresolved
  # symbols at build time.
  if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
    set_target_properties(${lib} PROPERTIES
      LINK_FLAGS "-undefined dynamic_lookup"
    )
  elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    # XXX: This is necessary mostly for openSUSE builds, see also
    # https://bugzilla.suse.com/show_bug.cgi?id=1012388.
    # Just strip out the linker flag to suppress this linker
    # option.
    string(REPLACE "-Wl,--no-undefined" ""
      CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS}"
    )
  endif()
  list(APPEND TESTLIBS ${lib})
endmacro()

BuildTestCLib(lib1 lib1.c)
BuildTestCLib(lib11 lib1.c lib11.c)
BuildTestCLib(lib2 lib2.c)
BuildTestCLib(lib21 lib2.c lib21.c)

# Create the exact copy of the lib2 library for tests
# in <attrib.lua>.
set(LIB2ORIG "${CMAKE_CURRENT_BINARY_DIR}/lib2${CMAKE_SHARED_LIBRARY_SUFFIX}")
set(LIB2COPY "${CMAKE_CURRENT_BINARY_DIR}/-lib2${CMAKE_SHARED_LIBRARY_SUFFIX}")
add_custom_command(
  OUTPUT ${LIB2COPY}
  COMMENT "Copying lib2 to -lib2 for PUC-Rio Lua 5.1 tests"
  COMMAND ${CMAKE_COMMAND} -E copy ${LIB2ORIG} ${LIB2COPY}
  DEPENDS ${TESTLIBS}
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)
list(APPEND TESTLIBS ${LIB2COPY})

# The original tarball contains subdirectory "libs" with an empty
# subdirectory "libs/P1", to be used by tests.
# Instead of tracking empty directory with some anchor-file for
# git, create this directory via CMake.
add_custom_target(PUC-Rio-Lua-5.1-tests-prepare DEPENDS ${TESTLIBS})
add_custom_command(TARGET PUC-Rio-Lua-5.1-tests-prepare
  COMMENT "Create directory for PUC-Rio Lua 5.1 tests"
  COMMAND ${CMAKE_COMMAND} -E make_directory P1
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# vim: expandtab tabstop=2 shiftwidth=2
