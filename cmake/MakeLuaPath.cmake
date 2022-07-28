# make_lua_path provides a convenient way to define LUA_PATH and
# LUA_CPATH variables.
#
# Example usage:
#
#   make_lua_path(LUA_PATH
#     PATH
#       ./?.lua
#       ${CMAKE_BINARY_DIR}/?.lua
#       ${CMAKE_CURRENT_SOURCE_DIR}/?.lua
#   )
#
# This will give you the string:
#    "./?.lua;${CMAKE_BINARY_DIR}/?.lua;${CMAKE_CURRENT_SOURCE_DIR}/?.lua;;"

function(make_lua_path path)
  set(prefix ARG)
  set(noValues)
  set(singleValues)
  set(multiValues PATHS)

  # FIXME: if we update to CMake >= 3.5, can remove this line.
  include(CMakeParseArguments)
  cmake_parse_arguments(${prefix}
                        "${noValues}"
                        "${singleValues}"
                        "${multiValues}"
                        ${ARGN})

  foreach(inc ${ARG_PATHS})
    # XXX: If one joins two strings with the semicolon, the value
    # automatically becomes a list. I found a single working
    # solution to make result variable be a string via "escaping"
    # the semicolon right in string interpolation.
    set(result "${result}${inc}\;")
  endforeach()

  if("${result}" STREQUAL "")
    message(FATAL_ERROR "No paths are given to <make_lua_path> helper.")
  endif()

  # XXX: This is the sentinel semicolon having special meaning
  # for LUA_PATH and LUA_CPATH variables. For more info, see the
  # link below:
  # https://www.lua.org/manual/5.1/manual.html#pdf-LUA_PATH
  set(${path} "${result}\;" PARENT_SCOPE)
endfunction()
