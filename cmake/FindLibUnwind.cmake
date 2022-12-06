#[========================================================================[.rst:
FindLibUnwind
--------
Finds the libunwind library.

Result Variables
^^^^^^^^^^^^^^^^
``LIBUNWIND_FOUND``
  True if the system has the libunwind library.
``LIBUNWIND_INCLUDE_DIR``
  Include directory needed to use libunwind.
``LIBUNWIND_LIBRARIES``
  Libraries needed to link to libunwind.

Cache Variables
^^^^^^^^^^^^^^^
``LIBUNWIND_INCLUDE_DIR``
  The directory containing ``libunwind.h``.
``LIBUNWIND_LIBRARIES``
  The paths to the libunwind libraries.
#]========================================================================]

include(FindPackageHandleStandardArgs)

find_package(PkgConfig QUIET)
pkg_check_modules(PC_LIBUNWIND QUIET libunwind)

find_path(LIBUNWIND_INCLUDE_DIR libunwind.h ${PC_LIBUNWIND_INCLUDE_DIRS})
if(LIBUNWIND_INCLUDE_DIR)
    include_directories(${LIBUNWIND_INCLUDE_DIR})
endif()

find_library(LIBUNWIND_LIBRARY NAMES unwind PATHS ${PC_LIBUNWIND_LIBRARY_DIRS})

set(LIBUNWIND_PLATFORM_LIBRARY_NAME "unwind-${CMAKE_SYSTEM_PROCESSOR}")
find_library(LIBUNWIND_PLATFORM_LIBRARY ${LIBUNWIND_PLATFORM_LIBRARY_NAME}
             ${PC_LIBUNWIND_LIBRARY_DIRS})
set(LIBUNWIND_LIBRARIES ${LIBUNWIND_LIBRARY} ${LIBUNWIND_PLATFORM_LIBRARY})

find_package_handle_standard_args(LibUnwind
      REQUIRED_VARS LIBUNWIND_INCLUDE_DIR LIBUNWIND_LIBRARIES)

mark_as_advanced(LIBUNWIND_INCLUDE_DIR LIBUNWIND_LIBRARIES)
