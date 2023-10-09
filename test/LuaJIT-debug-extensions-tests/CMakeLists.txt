SET(TEST_SUITE_NAME "LuaJIT-dbg-extension-tests")
add_test_suite_target(LuaJIT-dbg-extension-tests
  LABELS ${TEST_SUITE_NAME}
  DEPENDS ${LUAJIT_TEST_BINARY}
)

# Debug info is required for testing of extensions.
if(NOT (CMAKE_BUILD_TYPE MATCHES Debug))
  message(WARNING
    "not a DEBUG build, LuaJIT-lldb-extension-tests and "
    "LuaJIT-gdb-extension-tests are dummy"
  )
  return()
endif()

# MacOS asks for permission to debug a process even when the
# machine is set into development mode. To solve the issue,
# it is required to add relevant users to the `_developer` user
# group in MacOS. Disabled for now.
if(CMAKE_SYSTEM_NAME STREQUAL "Darwin" AND DEFINED ENV{CI})
  message(WARNING
    "Interactive debugging is unavailable for macOS CI builds,"
    "LuaJIT-lldb-extension-tests is dummy"
  )
  return()
endif()

find_package(PythonInterp)
if(NOT PYTHONINTERP_FOUND)
  message(WARNING
    "`python` is not found, LuaJIT-lldb-extension-tests and "
    "LuaJIT-gdb-extension-tests are dummy"
  )
  return()
endif()

set(DEBUGGER_TEST_ENV
  "LUAJIT_TEST_BINARY=${LUAJIT_TEST_BINARY}"
  # Suppresses __pycache__ generation.
  "PYTHONDONTWRITEBYTECODE=1"
  "DEBUGGER_EXTENSION_PATH=${PROJECT_SOURCE_DIR}/src/luajit_dbg.py"
)

set(TEST_SCRIPT_PATH
  ${PROJECT_SOURCE_DIR}/test/LuaJIT-debug-extensions-tests/debug-extension-tests.py
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
    DEPENDS LuaJIT-dbg-extension-tests-deps
  )
else()
  message(WARNING "`gdb' is not found, so LuaJIT-gdb-extension-tests is dummy")
endif()

find_program(LLDB lldb)
if(LLDB)
  set(test_title "test/${TEST_SUITE_NAME}/lldb")
  set(LLDB_TEST_ENV ${DEBUGGER_TEST_ENV} "DEBUGGER_COMMAND=${LLDB}")
  add_test(NAME "test/${TEST_SUITE_NAME}/lldb"
    COMMAND ${PYTHON_EXECUTABLE} ${TEST_SCRIPT_PATH}
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
  )
  set_tests_properties("${test_title}" PROPERTIES
    ENVIRONMENT "${LLDB_TEST_ENV}"
    LABELS ${TEST_SUITE_NAME}
    DEPENDS LuaJIT-dbg-extension-tests-deps
  )
else()
  message(WARNING "`lldb' is not found, so LuaJIT-lldb-extension-tests is dummy")
endif()
