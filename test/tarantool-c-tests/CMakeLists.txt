find_program(PROVE prove)
if(NOT PROVE)
  message(WARNING "`prove' is not found, so tarantool-c-tests target is not generated")
  return()
endif()

set(C_TEST_SUFFIX .c_test)
set(C_TEST_FLAGS --failures --shuffle)

if(CMAKE_VERBOSE_MAKEFILE)
  list(APPEND C_TEST_FLAGS --verbose)
endif()

# Build libtest.

set(TEST_LIB_NAME "test")
add_library(libtest STATIC EXCLUDE_FROM_ALL ${CMAKE_CURRENT_SOURCE_DIR}/test.c)
target_include_directories(libtest PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
set_target_properties(libtest PROPERTIES
  COMPILE_FLAGS "-Wall -Wextra"
  OUTPUT_NAME "${TEST_LIB_NAME}"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
)

# TARGET_C_FLAGS is required here to be sure that headers like
# lj_arch.h in compiled test are consistent with the LuaJIT library
# to link.
AppendFlags(TESTS_C_FLAGS ${TARGET_C_FLAGS})
# Use directory for absolute path to the Lua script helper. So,
# test binary can be run from any directory.
AppendFlags(TESTS_C_FLAGS "-D__LJ_TEST_DIR__='\"${CMAKE_CURRENT_SOURCE_DIR}\"'")

set(CTEST_SRC_SUFFIX ".test.c")
file(GLOB tests "${CMAKE_CURRENT_SOURCE_DIR}/*${CTEST_SRC_SUFFIX}")
foreach(test_source ${tests})
  # Get test name without suffix. Needed to set OUTPUT_NAME.
  get_filename_component(exe ${test_source} NAME_WE)
  add_executable(${exe} EXCLUDE_FROM_ALL ${test_source})
  target_include_directories(${exe} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${LUAJIT_SOURCE_DIR}
  )
  set_target_properties(${exe} PROPERTIES
    COMPILE_FLAGS "${TESTS_C_FLAGS}"
    OUTPUT_NAME "${exe}${C_TEST_SUFFIX}"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
  )
  target_link_libraries(${exe} libtest ${LUAJIT_LIBRARY})
  LIST(APPEND TESTS_COMPILED ${exe})
endforeach()

add_custom_target(tarantool-c-tests
  DEPENDS libluajit libtest ${TESTS_COMPILED}
)

add_custom_command(TARGET tarantool-c-tests
  COMMENT "Running Tarantool C tests"
  COMMAND
  ${PROVE}
    ${CMAKE_CURRENT_BINARY_DIR}
    --ext ${C_TEST_SUFFIX}
    --jobs ${CMAKE_BUILD_PARALLEL_LEVEL}
    # Report any TAP parse errors, if any, since test module is
    # maintained by us.
    --parse
    ${C_TEST_FLAGS}
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)
