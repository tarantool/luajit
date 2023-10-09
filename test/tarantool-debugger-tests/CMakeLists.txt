set(TEST_SUITE_NAME "tarantool-debugger-tests")

# Debug info is required for testing of extensions.
if(NOT (CMAKE_BUILD_TYPE MATCHES Debug))
  message(WARNING
    "Not a DEBUG build, tarantool-debugger-tests is omitted"
  )
  return()
endif()

# MacOS asks for permission to debug a process even when the
# machine is set into development mode. To solve the issue,
# it is required to add relevant users to the `_developer` user
# group in macOS. Disabled for now.
if(CMAKE_SYSTEM_NAME STREQUAL "Darwin" AND DEFINED ENV{CI})
  message(WARNING
    "Interactive debugging is unavailable for macOS CI builds,"
    " tarantool-debugger-tests is omitted"
  )
  return()
endif()

if(CMAKE_VERSION VERSION_LESS "3.12")
  # TODO: Can remove this after upgrading to CMake >= 3.12.
  find_package(PythonInterp)
  if(NOT PYTHONINTERP_FOUND)
    message(WARNING
      "`python' is not found, tarantool-debugger-tests is omitted"
    )
    return()
  endif()
else()
  find_package(Python COMPONENTS Interpreter)
  if(NOT PYTHON_FOUND)
    message(WARNING
      "`python' is not found, tarantool-debugger-tests is omitted"
    )
    return()
  endif()
  set(PYTHON_EXECUTABLE "${Python_EXECUTABLE}")
endif()

# XXX: The call produces both test and target
# <tarantool-debugger-tests-deps> as a side effect.
add_test_suite_target(tarantool-debugger-tests
  LABELS ${TEST_SUITE_NAME}
  DEPENDS ${LUAJIT_TEST_DEPS}
)

set(DEBUGGER_TEST_ENV
  "LUAJIT_TEST_BINARY=${LUAJIT_TEST_BINARY}"
  # Suppresses __pycache__ generation.
  "PYTHONDONTWRITEBYTECODE=1"
  "DEBUGGER_EXTENSION_PATH=${PROJECT_SOURCE_DIR}/src"
)

set(TEST_SCRIPT_PATH
  ${CMAKE_CURRENT_SOURCE_DIR}/debug-extension-tests.py
)

find_program(GDB gdb)
if(GDB)
  set(test_title "test/${TEST_SUITE_NAME}/gdb")
  set(GDB_TEST_ENV ${DEBUGGER_TEST_ENV} "DEBUGGER_COMMAND=${GDB}")
  add_test(NAME "${test_title}"
    COMMAND ${PYTHON_EXECUTABLE} ${TEST_SCRIPT_PATH}
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
  )
  set_tests_properties("${test_title}" PROPERTIES
    ENVIRONMENT "${GDB_TEST_ENV}"
    LABELS ${TEST_SUITE_NAME}
    DEPENDS tarantool-debugger-tests-deps
  )
else()
  message(WARNING
    "`gdb' is not found, so tarantool-debugger-tests/gdb is omitted"
  )
endif()

find_program(LLDB lldb)
if(LLDB)
  set(test_title "test/${TEST_SUITE_NAME}/lldb")
  set(LLDB_TEST_ENV ${DEBUGGER_TEST_ENV} "DEBUGGER_COMMAND=${LLDB}")
  add_test(NAME "${test_title}"
    COMMAND ${PYTHON_EXECUTABLE} ${TEST_SCRIPT_PATH}
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
  )
  set_tests_properties("${test_title}" PROPERTIES
    ENVIRONMENT "${LLDB_TEST_ENV}"
    LABELS ${TEST_SUITE_NAME}
    DEPENDS tarantool-debugger-tests-deps
  )
else()
  message(WARNING
    "`lldb' is not found, so tarantool-debugger-tests/lldb is omitted"
  )
endif()
