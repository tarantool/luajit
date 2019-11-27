#!/usr/bin/env tarantool

tap = require('tap')

test = tap.test("PAIRSMM-is-set")
test:plan(2)

-- There is no Lua way to detect whether LJ_PAIRSMM is enabled. However, in
-- tarantool build it's enabled by default. So the test scenario is following:
-- while we can overload the pairs/ipairs behaviour via metamethod as designed
-- in Lua 5.2, os.execute still preserves the Lua 5.1 interface.

local mt = {
	__pairs = function(self)
            local function stateless_iter(tbl, k)
                local v
                k, v = next(tbl, k)
                while k and v > 0 do k, v = next(tbl, k) end
                if v then return k,v end
            end
        return stateless_iter, self, nil
        end,
        __ipairs = function(self)
            local function stateless_iter(tbl, k)
                local v
                k, v = next(tbl, k)
                while k and v < 0 do k, v = next(tbl, k) end
                if v then return k,v end
            end
        return stateless_iter, self, nil
        end
}

local t = setmetatable({ }, mt)
t[1]  = 10
t[2]  = 20
t[3] = -10
t[4] = -20

local pairs_res = 0
local ipairs_res = 0
for k, v in pairs(t) do
    pairs_res = v + pairs_res
end
for k, v in ipairs(t) do
    ipairs_res = v + ipairs_res
end
test:is(pairs_res + ipairs_res, 0)
os_exec_res = os.execute()
test:is(os_exec_res, 1)
