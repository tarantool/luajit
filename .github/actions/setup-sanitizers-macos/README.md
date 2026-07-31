# Setup environment for sanitizers on macOS

Action setups the environment on macOS runners (install requirements, setup the
workflow environment, etc) for testing with sanitizers enabled.

Requires input:
- cc_name as versioned C compiler: gcc-ver or clang-ver.

## How to use Github Action from Github workflow

Add the following code to the running steps before LuaJIT configuration:
```
- uses: ./.github/actions/setup-sanitizers-macos
  if: ${{ matrix.OS == 'macOS' }}
```
