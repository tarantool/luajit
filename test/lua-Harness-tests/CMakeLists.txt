# Test suite that has been added from lua-Harness test suite
# in scope of https://github.com/tarantool/tarantool/issues/5844.

# See the rationale in the root CMakeLists.txt
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

find_program(PROVE prove)
if(NOT PROVE)
  message(WARNING "`prove' is not found, so lua-Harness-tests target is not generated")
  return()
endif()

# Tests create temporary files (see 303-package.t and 411-luajit.t
# for example) to be required. Also, they require some files from
# the original test source directory.
make_lua_path(LUA_PATH
  PATHS
    ./?.lua
    ${CMAKE_CURRENT_SOURCE_DIR}/?.lua
    ${LUAJIT_SOURCE_DIR}/?.lua
    ${LUAJIT_BINARY_DIR}/?.lua
)
set(LUA_TEST_FLAGS --failures --shuffle)

if(CMAKE_VERBOSE_MAKEFILE)
  list(APPEND LUA_TEST_FLAGS --verbose)
endif()

add_custom_target(lua-Harness-tests DEPENDS ${LUAJIT_TEST_BINARY})
add_custom_command(TARGET lua-Harness-tests
  COMMENT "Running lua-Harness tests"
  COMMAND
  env
    LUA_PATH="${LUA_PATH}"
    ${PROVE} ${CMAKE_CURRENT_SOURCE_DIR}
      --exec '${LUAJIT_TEST_COMMAND} -l profile_luajit21'
      --jobs ${CMAKE_BUILD_PARALLEL_LEVEL}
      ${LUA_TEST_FLAGS}
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# vim: expandtab tabstop=2 shiftwidth=2
