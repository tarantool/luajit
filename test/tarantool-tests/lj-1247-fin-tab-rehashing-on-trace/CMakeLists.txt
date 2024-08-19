get_filename_component(test_name ${CMAKE_CURRENT_SOURCE_DIR} NAME)
BuildTestCLib(lj_1247_allocinject lj_1247_allocinject.c ${test_name}.test.lua)
