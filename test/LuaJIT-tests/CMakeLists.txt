# See the rationale in the root CMakeLists.txt
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

add_subdirectory(src)

add_custom_target(LuaJIT-tests
  DEPENDS ${LUAJIT_TEST_BINARY} LuaJIT-tests-libs
)

make_lua_path(LUA_CPATH
  PATHS
  ${CMAKE_CURRENT_BINARY_DIR}/src/?${CMAKE_SHARED_LIBRARY_SUFFIX}
)

set(LUAJIT_TESTS_ENV
  "LUA_CPATH=\"${LUA_CPATH}\""
)

set(LD_LIBRARY_PATH "${CMAKE_CURRENT_BINARY_DIR}/src/:")

if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
  list(APPEND LUAJIT_TESTS_ENV DYLD_LIBRARY_PATH="${LD_LIBRARY_PATH}")
else()
  list(APPEND LUAJIT_TESTS_ENV LD_LIBRARY_PATH="${LD_LIBRARY_PATH}")
endif()

add_custom_command(TARGET LuaJIT-tests
  COMMENT "Running LuaJIT-tests"
  COMMAND
    env
      ${LUAJIT_TESTS_ENV}
      ${LUAJIT_TEST_COMMAND} ${CMAKE_CURRENT_SOURCE_DIR}/test.lua
      +slow +ffi +bit +jit
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
)
