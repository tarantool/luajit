#!/usr/bin/env tarantool

-- Miscellaneous test for LuaJIT bugs
local tap = require('tap')
local misc = require('misc')

local test = tap.test("gh-4738-incorrect-result-tonumber64")
test:plan(24)
--
-- gh-4738: Make sure that tonumber64 always returns cdata.
--
test:ok(misc.tonumber64(1) == 1)
test:ok(misc.tonumber64(-1) == -1)
test:ok(misc.tonumber64(1.5) == 1)
test:ok(misc.tonumber64(-1.5) == -1)
test:ok(misc.tonumber64(1LL) == 1)
test:ok(misc.tonumber64(1ULL) == 1)
test:ok(misc.tonumber64(1LLU) == 1)
test:ok(misc.tonumber64(-1ULL) == 18446744073709551615ULL)
test:ok(misc.tonumber64('1') == 1)
test:ok(misc.tonumber64('1LL') == 1)
test:ok(misc.tonumber64('1ULL') == 1)
test:ok(misc.tonumber64('-1ULL') == 18446744073709551615ULL)

test:is(type(misc.tonumber64(1)), 'cdata')
test:is(type(misc.tonumber64(-1)), 'cdata')
test:is(type(misc.tonumber64(1.5)), 'cdata')
test:is(type(misc.tonumber64(-1.5)), 'cdata')
test:is(type(misc.tonumber64(1LL)), 'cdata')
test:is(type(misc.tonumber64(1ULL)), 'cdata')
test:is(type(misc.tonumber64(1LLU)), 'cdata')
test:is(type(misc.tonumber64(-1ULL)), 'cdata')
test:is(type(misc.tonumber64('1')), 'cdata')
test:is(type(misc.tonumber64('1LL')), 'cdata')
test:is(type(misc.tonumber64('1ULL')), 'cdata')
test:is(type(misc.tonumber64('-1ULL')), 'cdata')

os.exit(test:check() and 0 or 1)
