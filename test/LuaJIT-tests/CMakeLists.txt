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
      # CMAKE_C_COMPILER is used because it has the same behaviour
      # as CMAKE_CXX_COMPILER, but CMAKE_CXX_COMPILER is not
      # required for building LuaJIT and can be missed in GH
      # Actions.
      COMMAND ${CMAKE_C_COMPILER} -print-file-name=${lib}
      OUTPUT_VARIABLE LIB_LINK
      OUTPUT_STRIP_TRAILING_WHITESPACE
      RESULT_VARIABLE RES
    )

    if(NOT RES EQUAL 0)
      message(FATAL_ERROR
        "Executing '${CMAKE_C_COMPILER} -print-file-name=${lib}' has failed"
      )
    endif()

    # GCC and Clang return a passed filename when a library is
    # not found.
    if(LIB_LINK STREQUAL ${lib})
      message(FATAL_ERROR "Library '${lib}' is not found")
    endif()

    # Fortunately, we are not interested in macOS here, so we can
    # use realpath. Beware, `realpath` always returns an exit code
    # equal to 0, so we cannot check if it fails.
    execute_process(
      COMMAND realpath ${LIB_LINK}
      OUTPUT_VARIABLE ${output}
      OUTPUT_STRIP_TRAILING_WHITESPACE
    )

    unset(LIB_LINK)
    unset(RES)
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
