local tap = require("tap")
local test = tap.test("clib-misc-sysprof"):skipcond({
  ["Sysprof is implemented for x86_64 only"] = jit.arch ~= "x86" and
                                               jit.arch ~= "x64",
  ["Sysprof is implemented for Linux only"] = jit.os ~= "Linux",
})

test:plan(2)

local testsysprof = require("testsysprof")

local jit = require('jit')

jit.off()

test:ok(testsysprof.base())
test:ok(testsysprof.validation())

-- FIXME: The following two tests are disabled because sometimes
-- `backtrace` dynamically loads a platform-specific unwinder, which is
-- not signal-safe.
--[[
local function lua_payload(n)
  if n <= 1 then
    return n
  end
  return lua_payload(n - 1) + lua_payload(n - 2)
end

local function payload()
  local n_iterations = 500000

  local co = coroutine.create(function ()
    for i = 1, n_iterations do
      if i % 2 == 0 then
        testsysprof.c_payload(10)
      else
        lua_payload(10)
      end
      coroutine.yield()
    end
  end)

  for _ = 1, n_iterations do
    coroutine.resume(co)
  end
end

test:ok(testsysprof.profile_func(payload))

jit.on()
jit.flush()

test:ok(testsysprof.profile_func(payload))
--]]
os.exit(test:check() and 0 or 1)
