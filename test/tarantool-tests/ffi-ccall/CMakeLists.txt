list(APPEND tests
  ffi-ccall-arm64-fp-convention.test.lua
  lj-205-arm64-osx-ffi-enum-arg.test.lua
  lj-205-arm64-osx-ffi-small-arg.test.lua
  lj-1357-arm64-struct-array-pass-by-val.test.lua
)

BuildTestCLib(libfficcall libfficcall.c "${tests}")
