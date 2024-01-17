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

if(LUAJIT_USE_ASAN)
  # When running LuaJIT-tests under ASAN, the internal ASAN check
  # failed:
  # AddressSanitizer: CHECK failed: asan_interceptors.cpp:356
  # "((__interception::real___cxa_throw)) != (0)" (0x0, 0x0)
  # This is a workaround suggested at
  # https://github.com/google/sanitizers/issues/934.
  macro(LibRealPath output lib)
    execute_process(
      COMMAND ${CMAKE_CXX_COMPILER} -print-file-name=${lib}
      OUTPUT_VARIABLE LIB_LINK
      OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    # Fortunately, we are not interested in macOS here, so we can
    # use realpath.
    execute_process(
      COMMAND realpath ${LIB_LINK}
      OUTPUT_VARIABLE ${output}
      OUTPUT_STRIP_TRAILING_WHITESPACE
    )
  endmacro()
  LibRealPath(LIB_STDCPP libstdc++.so)
  # XXX: GCC requires both. Clang requires only libstdc++.
  if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
    LibRealPath(LIB_ASAN libasan.so)
    # XXX: Don't use " " (separator in LD_PRELOAD) in `list()`.
    # ";" will expand to " " as we want.
    list(APPEND LUAJIT_TESTS_ENV LD_PRELOAD="${LIB_ASAN};${LIB_STDCPP}")
  else()
    list(APPEND LUAJIT_TESTS_ENV LD_PRELOAD="${LIB_STDCPP}")
  endif()
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
