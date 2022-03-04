# Building tools for developing with LuaJIT.
# Major portions taken verbatim or adapted from the uJIT.
# Copyright (C) 2020-2021 LuaVela Authors.
# Copyright (C) 2015-2020 IPONWEB Ltd.

# See the rationale in the root CMakeLists.txt.
cmake_minimum_required(VERSION 3.1 FATAL_ERROR)

set(LUAJIT_TOOLS_DEPS)

if(LUAJIT_DISABLE_MEMPROF)
  message(STATUS "LuaJIT memory profiler support is disabled")
else()
  # XXX: Can use genex here since the value need to be evaluated
  # at the configuration phase. Fortunately, we know the exact
  # path where LuaJIT binary is located.
  set(LUAJIT_TOOLS_BIN ${LUAJIT_BINARY_DIR}/${LUAJIT_CLI_NAME})
  set(LUAJIT_TOOLS_DIR ${CMAKE_CURRENT_SOURCE_DIR})
  # XXX: Unfortunately, there is no convenient way to set
  # particular permissions to the output file via CMake.
  # Furthermore, I even failed to copy the given file to the same
  # path to change its permissions. After looking at the docs, I
  # realized that the valid solution would be too monstrous for
  # such a simple task. As a result I've made the template itself
  # executable, so the issue is resolved.
  configure_file(luajit-parse-memprof.in luajit-parse-memprof @ONLY ESCAPE_QUOTES)

  add_custom_target(tools-parse-memprof EXCLUDE_FROM_ALL DEPENDS
    luajit-parse-memprof
    memprof/humanize.lua
    memprof/parse.lua
    memprof.lua
    utils/avl.lua
    utils/bufread.lua
    utils/symtab.lua
  )
  list(APPEND LUAJIT_TOOLS_DEPS tools-parse-memprof)

  install(FILES
      ${CMAKE_CURRENT_SOURCE_DIR}/memprof/humanize.lua
      ${CMAKE_CURRENT_SOURCE_DIR}/memprof/parse.lua
    DESTINATION ${LUAJIT_DATAROOTDIR}/memprof
    PERMISSIONS
      OWNER_READ OWNER_WRITE
      GROUP_READ
      WORLD_READ
    COMPONENT tools-parse-memprof
  )
  install(FILES
      ${CMAKE_CURRENT_SOURCE_DIR}/utils/avl.lua
      ${CMAKE_CURRENT_SOURCE_DIR}/utils/bufread.lua
      ${CMAKE_CURRENT_SOURCE_DIR}/utils/symtab.lua
    DESTINATION ${LUAJIT_DATAROOTDIR}/utils
    PERMISSIONS
      OWNER_READ OWNER_WRITE
      GROUP_READ
      WORLD_READ
    COMPONENT tools-parse-memprof
  )
  install(FILES
      ${CMAKE_CURRENT_SOURCE_DIR}/memprof.lua
    DESTINATION ${LUAJIT_DATAROOTDIR}
    PERMISSIONS
      OWNER_READ OWNER_WRITE
      GROUP_READ
      WORLD_READ
    COMPONENT tools-parse-memprof
  )
  install(CODE
    # XXX: The auxiliary script needs to be configured for to be
    # used in repository directly. Furthermore, it needs to be
    # reconfigured prior to its installation. The temporary
    # <configure_file> output is stored to the project build
    # directory and removed later after being installed. This
    # script will have gone as a result of the issue:
    # https://github.com/tarantool/tarantool/issues/5688.
    "
      set(LUAJIT_TOOLS_BIN ${CMAKE_INSTALL_PREFIX}/bin/${LUAJIT_CLI_NAME})
      set(LUAJIT_TOOLS_DIR ${CMAKE_INSTALL_PREFIX}/${LUAJIT_DATAROOTDIR})
      configure_file(${CMAKE_CURRENT_SOURCE_DIR}/luajit-parse-memprof.in
        ${PROJECT_BINARY_DIR}/luajit-parse-memprof @ONLY ESCAPE_QUOTES)
      file(INSTALL ${PROJECT_BINARY_DIR}/luajit-parse-memprof
        DESTINATION ${CMAKE_INSTALL_PREFIX}/bin
        USE_SOURCE_PERMISSIONS
      )
      file(REMOVE ${PROJECT_BINARY_DIR}/luajit-parse-memprof)
    "
    COMPONENT tools-parse-memprof
  )
endif()

add_custom_target(LuaJIT-tools DEPENDS ${LUAJIT_TOOLS_DEPS})
