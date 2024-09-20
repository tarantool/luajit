if (NOT(CMAKE_SYSTEM_NAME STREQUAL "Darwin"))
  BuildTestCLib(resstripped resstripped.c)
  # Unfortunately, <target_link_options> command is introduced
  # since CMake 3.13, so we can't use it now considering ancient
  # distros support. Just build linker flags by hands.
  set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -s")
endif()
