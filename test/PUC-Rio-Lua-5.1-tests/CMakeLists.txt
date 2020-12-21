# Test suite that has been added from PUC-Rio Lua 5.1 test archive
# in scope of https://github.com/tarantool/tarantool/issues/5845.

# See the rationale in the root CMakeLists.txt.
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

# XXX: There are two ways to set up the proper environment
# described in the suite's README:
# * set LUA_PATH to "?;./?.lua"
# * or, better yet, set LUA_PATH to "./?.lua;;" and LUA_INIT to
#   "package.path = '?;'..package.path"
# Unfortunately, Tarantool doesn't support LUA_INIT and most
# likely it never will. For more info, see
# https://github.com/tarantool/tarantool/issues/5744
# Hence, there is no way other than set LUA_PATH environment
# variable as proposed in the first case.
set(LUA_PATH "?\;${CMAKE_CURRENT_SOURCE_DIR}/?.lua")

# Establish PUC-Rio-Lua-5.1-tests-prepare target that creates
# <libs/P1> subdirectory.
add_subdirectory(libs)

# TODO: PUC-Rio Lua 5.1 test suite also has special header
# <ltests.h> and <ltests.c> translation unit to check some
# internal behaviour of the Lua implementation (see etc/
# directory). It modifies realloc function to check memory
# consistency and also contains tests for yield in hooks
# and for the Lua C API.
# But, unfortunately, <ltests.c> depends on specific PUC-Rio
# Lua 5.1 internal headers and should be adapted for LuaJIT.

add_custom_target(PUC-Rio-Lua-5.1-tests
  DEPENDS ${LUAJIT_TEST_BINARY} PUC-Rio-Lua-5.1-tests-prepare
)

add_custom_command(TARGET PUC-Rio-Lua-5.1-tests
  COMMENT "Running PUC-Rio Lua 5.1 tests"
  COMMAND
  env
    LUA_PATH="${LUA_PATH}\;\;"
    ${LUAJIT_TEST_COMMAND} ${CMAKE_CURRENT_SOURCE_DIR}/all.lua
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# vim: expandtab tabstop=2 shiftwidth=2
