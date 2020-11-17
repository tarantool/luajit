# Running various test suites against LuaJIT.

# See the rationale in the root CMakeLists.txt.
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

add_subdirectory(tarantool-tests)

add_custom_target(${PROJECT_NAME}-test DEPENDS
  tarantool-tests
)

if(LUAJIT_USE_TEST)
  if(POLICY CMP0037)
    if(CMAKE_VERSION VERSION_LESS 3.11)
      # CMake below 3.11 reserves the name 'test'. Use old policy.
      # https://cmake.org/cmake/help/v3.11/release/3.11.html#other-changes
      cmake_policy(SET CMP0037 OLD)
    else()
      # Starting from CMake 3.11 the name 'test' is reserved in
      # special cases and can be used as a target name.
      cmake_policy(SET CMP0037 NEW)
    endif()
  endif(POLICY CMP0037)

  add_custom_target(test DEPENDS
    ${PROJECT_NAME}-test
  )
endif()
