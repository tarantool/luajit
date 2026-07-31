# Setup environment for sanitizers on Linux

Action setups the environment on Linux runners (install requirements, setup the
workflow environment, etc) for testing with sanitizers enabled.

Optional input:
- cc_name as versioned C compiler: gcc-ver or clang-ver.

## How to use Github Action from Github workflow

Add the following code to the running steps before LuaJIT configuration:
```
- uses: ./.github/actions/setup-sanitizers-linux
  if: ${{ matrix.OS == 'Linux' }}
```

Pass `CMAKE_PREFIX_PATH` and `CMAKE_C_COMPILER` to CMake:
```
  -DCMAKE_C_COMPILER=${CMAKE_C_COMPILER}
  -DCMAKE_PREFIX_PATH=${CMAKE_PREFIX_PATH}
```
