#! /usr/bin/lua
--
-- lua-Harness : <https://fperrad.frama.io/lua-Harness/>
--
-- Copyright (C) 2018-2020, Perrad Francois
--
-- This code is licensed under the terms of the MIT/X11 license,
-- like Lua itself.
--

--[[

=head1 JIT Library

=head2 Synopsis

    % prove 403-jit.t

=head2 Description

See L<http://luajit.org/ext_jit.html>.

=cut

--]]

require 'tap'
local profile = require'profile'

if not jit then
    skip_all("only with LuaJIT")
end

local compiled_with_jit = jit.status()
local luajit20 = jit.version_num < 20100 and not jit.version:match'RaptorJIT'
local has_jit_opt = compiled_with_jit
local has_jit_security = jit.security
local has_jit_util = not ujit and not jit.version:match'RaptorJIT'

plan'no_plan'

is(package.loaded.jit, _G.jit, "package.loaded")
is(require'jit', jit, "require")

do -- arch
    type_ok(jit.arch, 'string', "arch")
end

do -- flush
    type_ok(jit.flush, 'function', "flush")
end

do -- off
    jit.off()
    is(jit.status(), false, "off")
end

-- on
if compiled_with_jit then
    jit.on()
    is(jit.status(), true, "on")
else
    error_like(function () jit.on() end,
               "^[^:]+:%d+: JIT compiler permanently disabled by build option",
               "no jit.on")
end

-- opt
if has_jit_opt then
    type_ok(jit.opt, 'table', "opt.*")
    type_ok(jit.opt.start, 'function', "opt.start")
else
    is(jit.opt, nil, "no jit.opt")
end

do -- os
    type_ok(jit.os, 'string', "os")
end

-- prngstate
if profile.openresty then
    type_ok(jit.prngstate(), 'table', "prngstate")
    local s1 = { 1, 2, 3, 4, 5, 6, 7, 8}
    type_ok(jit.prngstate(s1), 'table')
    local s2 = { 8, 7, 6, 5, 4, 3, 2, 1}
    eq_array(jit.prngstate(s2), s1)
    eq_array(jit.prngstate(), s2)

    type_ok(jit.prngstate(32), 'table', "backward compat")
    eq_array(jit.prngstate(5617), { 32, 0, 0, 0, 0, 0, 0, 0 })
    eq_array(jit.prngstate(), { 5617, 0, 0, 0, 0, 0, 0, 0 })

    error_like(function () jit.prngstate(-1) end,
               "^[^:]+:%d+: bad argument #1 to 'prngstate' %(PRNG state must be an array with up to 8 integers or an integer%)")

    error_like(function () jit.prngstate(false) end,
               "^[^:]+:%d+: bad argument #1 to 'prngstate' %(table expected, got boolean%)")
elseif jit.version:match'moonjit' then
    is(jit.prngstate(), 0, "prngstate")
else
    is(jit.prngstate, nil, "no jit.prngstate");
end

-- security
if has_jit_security then
    type_ok(jit.security, 'function', "security")
    type_ok(jit.security('prng'), 'number', "prng")
    type_ok(jit.security('strhash'), 'number', "strhash")
    type_ok(jit.security('strid'), 'number', "stdid")
    type_ok(jit.security('mcode'), 'number', "mcode")

    error_like(function () jit.security('foo') end,
               "^[^:]+:%d+: bad argument #1 to 'security' %(invalid option 'foo'%)")
else
    is(jit.security, nil, "no jit.security")
end

do -- status
    local status = { jit.status() }
    type_ok(status[1], 'boolean', "status")
    if compiled_with_jit then
        for i = 2, #status do
            type_ok(status[i], 'string', status[i])
        end
    else
        is(#status, 1)
    end
end

-- util
if has_jit_util then
    local jutil = require'jit.util'
    type_ok(jutil, 'table', "util")
    is(package.loaded['jit.util'], jutil)

    if luajit20 then
        is(jit.util, jutil, "util inside jit")
    else
        is(jit.util, nil, "no util inside jit")
    end
else
    local r = pcall(require, 'jit.util')
    is(r, false, "no jit.util")
end

do -- version
    type_ok(jit.version, 'string', "version")
    like(jit.version, '^%w+ %d%.%d%.%d')
end

do -- version_num
    type_ok(jit.version_num, 'number', "version_num")
    like(string.format("%06d", jit.version_num), '^0[12]0[012]%d%d$')
end

done_testing()

-- Local Variables:
--   mode: lua
--   lua-indent-level: 4
--   fill-column: 100
-- End:
-- vim: ft=lua expandtab shiftwidth=4:
