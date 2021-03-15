#! /usr/bin/lua
--
-- lua-Harness : <https://fperrad.frama.io/lua-Harness/>
--
-- Copyright (C) 2019-2020, Perrad Francois
--
-- This code is licensed under the terms of the MIT/X11 license,
-- like Lua itself.
--

--[[

=head1 JIT Library extensions

=head2 Synopsis

    % prove 404-ext.t

=head2 Description

See L<http://luajit.org/ext_jit.html>.

=cut

--]]

require 'tap'
local profile = require'profile'

local luajit21 = jit and (jit.version_num >= 20100 or jit.version:match'^RaptorJIT')
if not luajit21 then
    skip_all("only with LuaJIT 2.1")
end

plan'no_plan'

do -- table.new
    local r, new = pcall(require, 'table.new')
    is(r, true, 'table.new')
    type_ok(new, 'function')
    is(package.loaded['table.new'], new)

    type_ok(new(100, 0), 'table')
    type_ok(new(0, 100), 'table')
    type_ok(new(200, 200), 'table')

    error_like(function () new(42) end,
               "^[^:]+:%d+: bad argument #2 to 'new' %(number expected, got no value%)")
end

do -- table.clear
    local r, clear = pcall(require, 'table.clear')
    is(r, true, 'table.clear')
    type_ok(clear, 'function')
    is(package.loaded['table.clear'], clear)

    local t = { 'foo', bar = 42 }
    is(t[1], 'foo')
    is(t.bar, 42)
    clear(t)
    is(t[1], nil)
    is(t.bar, nil)

    error_like(function () clear(42) end,
               "^[^:]+:%d+: bad argument #1 to 'clear' %(table expected, got number%)")
end

-- table.clone
if profile.openresty then
    local r, clone = pcall(require, 'table.clone')
    is(r, true, 'table.clone')
    type_ok(clone, 'function')
    is(package.loaded['table.clone'], clone)

    local mt = {}
    local t = setmetatable({ 'foo', bar = 42 }, mt)
    is(t[1], 'foo')
    is(t.bar, 42)
    local t2 = clone(t)
    type_ok(t2, 'table')
    isnt(t2, t)
    is(getmetatable(t2), nil)
    is(t2[1], 'foo')
    is(t2.bar, 42)

    error_like(function () clone(42) end,
               "^[^:]+:%d+: bad argument #1 to 'clone' %(table expected, got number%)")
else
    is(pcall(require, 'table.clone'), false, 'no table.clone')
end

-- table.isarray
if profile.openresty then
    local r, isarray = pcall(require, 'table.isarray')
    is(r, true, 'table.isarray')
    type_ok(isarray, 'function')
    is(package.loaded['table.isarray'], isarray)

    is(isarray({ [3] = 3, [5.3] = 4 }), false)
    is(isarray({ [3] = 'a', [5] = true }), true)
    is(isarray({ 'a', nil, true, 3.14 }), true)
    is(isarray({}), true)
    is(isarray({ ['1'] = 3, ['2'] = 4 }), false)
    is(isarray({ ['dog'] = 3, ['cat'] = 4 }), false)
    is(isarray({ 'dog', 'cat', true, ['bird'] = 3 }), false)

    error_like(function () isarray(42) end,
               "^[^:]+:%d+: bad argument #1 to 'isarray' %(table expected, got number%)")
else
    is(pcall(require, 'table.isarray'), false, 'no table.isarray')
end

-- table.isempty
if profile.openresty then
    local r, isempty = pcall(require, 'table.isempty')
    is(r, true, 'table.isempty')
    type_ok(isempty, 'function')
    is(package.loaded['table.isempty'], isempty)

    is(isempty({}), true)
    is(isempty({ nil }), true)
    is(isempty({ dogs = nil }), true)
    is(isempty({ 3.1 }), false)
    is(isempty({ 'a', 'b' }), false)
    is(isempty({ nil, false }), false)
    is(isempty({ dogs = 3 }), false)
    is(isempty({ dogs = 3, cats = 4 }), false)
    is(isempty({ dogs = 3, 5 }), false)

    error_like(function () isempty(42) end,
               "^[^:]+:%d+: bad argument #1 to 'isempty' %(table expected, got number%)")
else
    is(pcall(require, 'table.isempty'), false, 'no table.isempty')
end

-- table.nkeys
if profile.openresty then
    local r, nkeys = pcall(require, 'table.nkeys')
    is(r, true, 'table.nkeys')
    type_ok(nkeys, 'function')
    is(package.loaded['table.nkeys'], nkeys)

    is(nkeys({}), 0)
    is(nkeys({ cats = 4 }), 1)
    is(nkeys({ dogs = 3, cats = 4 }), 2)
    is(nkeys({ dogs = nil, cats = 4 }), 1)
    is(nkeys({ 'cats' }), 1)
    is(nkeys({ 'dogs', 3, 'cats', 4 }), 4)
    is(nkeys({ 'dogs', nil, 'cats', 4 }), 3)
    is(nkeys({ cats = 4, 5, 6 }), 3)
    is(nkeys({ nil, 'foo', dogs = 3, cats = 4 }), 3)

    error_like(function () nkeys(42) end,
               "^[^:]+:%d+: bad argument #1 to 'nkeys' %(table expected, got number%)")
else
    is(pcall(require, 'table.nkeys'), false, 'no table.nkeys')
end

-- thread.exdata
if pcall(require, 'ffi') and (profile.openresty or jit.version:match'moonjit') then
    make_specific_checks'lexicojit/ext.t'
end

done_testing()

-- Local Variables:
--   mode: lua
--   lua-indent-level: 4
--   fill-column: 100
-- End:
-- vim: ft=lua expandtab shiftwidth=4:
