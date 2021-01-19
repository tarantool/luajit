--
-- lua-Harness : <https://fperrad.frama.io/lua-Harness/>
--
-- Copyright (C) 2019-2020, Perrad Francois
--
-- This code is licensed under the terms of the MIT/X11 license,
-- like Lua itself.
--

do -- toclose
    local called = false
    do
        local foo <close> = setmetatable({}, { __close = function () called = true end })
        type_ok(foo, 'table', "toclose")
        is(called, false)
    end
    is(called, true)

    error_like(function () do local foo <close> = {} end end,
               "^[^:]+:%d+: variable 'foo' got a non%-closable value")

    lives_ok(function ()
        local var1 <const> = nil
        local var2 <const> = nil
        do
            local var3 <close> = setmetatable({}, { __close = function () end })
        end
        local var4 = true
        -- attempt to close non-closable variable 'var4'
    end, "blocker bug 5.4.0-rc3")
end

-- Local Variables:
--   mode: lua
--   lua-indent-level: 4
--   fill-column: 100
-- End:
-- vim: ft=lua expandtab shiftwidth=4:
