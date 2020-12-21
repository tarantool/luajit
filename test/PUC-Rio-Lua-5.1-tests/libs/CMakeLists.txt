# Test suite that has been added from PUC-Rio Lua 5.1 test archive
# in scope of https://github.com/tarantool/tarantool/issues/5845.

# See the rationale in the root CMakeLists.txt.
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

# The original tarball contains subdirectory "libs" with an empty
# subdirectory "libs/P1", to be used by tests.
# Instead of tracking empty directory with some anchor-file for
# git, create this directory via CMake.
add_custom_target(PUC-Rio-Lua-5.1-tests-prepare)
add_custom_command(TARGET PUC-Rio-Lua-5.1-tests-prepare
  COMMENT "Create directory for PUC-Rio Lua 5.1 tests"
  COMMAND ${CMAKE_COMMAND} -E make_directory P1
  WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# vim: expandtab tabstop=2 shiftwidth=2
