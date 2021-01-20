# See the rationale in the root CMakeLists.txt
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

add_custom_target(LuaJIT-tests DEPENDS ${LUAJIT_TEST_BINARY})

add_custom_command(TARGET LuaJIT-tests
  COMMENT "Running LuaJIT-tests"
  COMMAND
    ${LUAJIT_TEST_COMMAND} ${CMAKE_CURRENT_SOURCE_DIR}/test.lua
    +slow +ffi +bit +jit
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
)
