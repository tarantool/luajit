list(APPEND tests
  ffi-call-empty-struct.test.lua
  ffi-ccall-arm64-fp-convention.test.lua
  ffi-vector-arguments.test.lua
  lj-205-arm64-osx-ffi-enum-arg.test.lua
  lj-205-arm64-osx-ffi-small-arg.test.lua
  lj-1357-arm64-struct-array-pass-by-val.test.lua
  lj-1455-arm64-ffi-ccall-hfa.test.lua
  lj-1455-ffi-conventions.test.lua
)

BuildTestCLib(libfficcall libfficcall.c "${tests}")
