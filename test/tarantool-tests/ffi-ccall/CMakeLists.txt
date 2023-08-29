list(APPEND tests
  ffi-ccall-arm64-fp-convention.test.lua
  lj-205-arm64-osx-ffi-enum-arg.test.lua
  lj-205-arm64-osx-ffi-small-arg.test.lua
)

BuildTestCLib(libfficcall libfficcall.c "${tests}")
