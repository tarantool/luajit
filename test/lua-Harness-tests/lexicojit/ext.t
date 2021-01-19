--
-- lua-Harness : <https://fperrad.frama.io/lua-Harness/>
--
-- Copyright (C) 2019-2020, Perrad Francois
--
-- This code is licensed under the terms of the MIT/X11 license,
-- like Lua itself.
--

local profile = require'profile'

do -- thread.exdata
    local r, exdata = pcall(require, 'thread.exdata')
    is(r, true, 'thread.exdata')
    type_ok(exdata, 'function')
    is(package.loaded['thread.exdata'], exdata)

    local ffi = require'ffi'
    local u64 = ffi.new('uintptr_t', 0xefdeaddeadbeefLL)
    local ptr = ffi.cast('void *', u64)
    exdata(u64)  -- set
    is(exdata(), ptr) -- get

    error_like(function () exdata(42) end,
               "^[^:]+:%d+: bad argument #1 to 'exdata' %(cdata expected, got number%)")
end

-- thread.exdata2
if profile.openresty then
    local r, exdata2 = pcall(require, 'thread.exdata2')
    is(r, true, 'thread.exdata2')
    type_ok(exdata2, 'function')
    is(package.loaded['thread.exdata2'], exdata2)

    local ffi = require'ffi'
    local u64 = ffi.new('uintptr_t', 0xefdeaddeadbeefLL)
    local ptr = ffi.cast('void *', u64)
    exdata2(u64)  -- set
    is(exdata2(), ptr) -- get

    error_like(function () exdata2(42) end,
               "^[^:]+:%d+: bad argument #1 to 'exdata2' %(cdata expected, got number%)")
else
    is(pcall(require, 'thread.exdata2'), false, 'no thread.exdata2')
end

-- Local Variables:
--   mode: lua
--   lua-indent-level: 4
--   fill-column: 100
-- End:
-- vim: ft=lua expandtab shiftwidth=4:
