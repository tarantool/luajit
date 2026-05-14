# Setup environment for testing debugger extension on Linux

Action setups the environment on Linux runners (install requirements, setup the
workflow environment, etc.) for testing the python debugger extension for
various debuggers.

## How to use Github Action from Github workflow

Add the following code to the running steps before LuaJIT configuration:
```
- uses: ./.github/actions/setup-debuggers
  if: ${{ matrix.OS == 'Linux' }}
```
