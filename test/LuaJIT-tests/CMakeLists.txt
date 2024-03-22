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
  LibRealPath(LIB_STDCPP libstdc++.so)
  # XXX: GCC requires both. Clang requires only libstdc++.
  # Be aware, ASAN runtime in Clang on Linux was offered only in
  # the form of a library with differ name from libasan.so (e.g.
  # libclang_rt.asan-x86_64.a).
  # See also:
  # https://github.com/google/sanitizers/wiki/AddressSanitizerAsDso.
  if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
    LibRealPath(LIB_ASAN libasan.so)
    # XXX: The items of the list in LD_PRELOAD can be separated
    # by spaces or colons, and there is no support for escaping
    # either separator, see ld.so(8).
    list(APPEND LUAJIT_TESTS_ENV LD_PRELOAD=${LIB_ASAN}:${LIB_STDCPP})
  else()
    list(APPEND LUAJIT_TESTS_ENV LD_PRELOAD=${LIB_STDCPP})
  endif()
endif()

if(LUAJIT_NO_UNWIND)
  # Test <catch_cpp.lua> verifies the interoperability with C++
  # ABI exceptions, so it requires external unwinding enabled.
  # Hence, skip them otherwise.
  set(LUAJIT_TEST_TAGS_EXTRA +internal_unwinder)
endif()

add_custom_command(TARGET LuaJIT-tests
  COMMENT "Running LuaJIT-tests"
  COMMAND
    env
      ${LUAJIT_TESTS_ENV}
      ${LUAJIT_TEST_COMMAND} ${CMAKE_CURRENT_SOURCE_DIR}/test.lua
      +slow +ffi +bit +jit ${LUAJIT_TEST_TAGS_EXTRA}
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
)
