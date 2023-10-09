# This file provides tests for LuaJIT debug extensions for lldb and gdb.
import os
import re
import subprocess
import sys
import tempfile
import unittest

from threading import Timer

LEGACY = re.match(r'^2\.', sys.version)

LUAJIT_BINARY = os.environ['LUAJIT_TEST_BINARY']
EXTENSION = os.environ['DEBUGGER_EXTENSION_PATH']
DEBUGGER = os.environ['DEBUGGER_COMMAND']
LLDB = 'lldb' in DEBUGGER
TIMEOUT = 10

RUN_CMD_FILE = '-s' if LLDB else '-x'
INFERIOR_ARGS = '--' if LLDB else '--args'
PROCESS_RUN = 'process launch' if LLDB else 'r'
LOAD_EXTENSION = (
    'command script import {ext}' if LLDB else 'source {ext}'
).format(ext=EXTENSION)


def persist(data):
    tmp = tempfile.NamedTemporaryFile(mode='w')
    tmp.write(data)
    tmp.flush()
    return tmp


def execute_process(cmd, timeout=TIMEOUT):
    if LEGACY:
        # XXX: The Python 2.7 version of `subprocess.Popen` doesn't have a
        # timeout option, so the required functionality was implemented via
        # `threading.Timer`.
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        timer = Timer(TIMEOUT, process.kill)
        timer.start()
        stdout, _ = process.communicate()
        timer.cancel()

        # XXX: If the timeout is exceeded and the process is killed by the
        # timer, then the return code is non-zero, and we are going to blow up.
        assert process.returncode == 0
        return stdout.decode('ascii')
    else:
        process = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
        return process.stdout.decode('ascii')


def filter_debugger_output(output):
    descriptor = '(lldb)' if LLDB else '(gdb)'
    return ''.join(
        filter(
            lambda line: not line.startswith(descriptor),
            output.splitlines(True),
        ),
    )


class TestCaseBase(unittest.TestCase):
    @classmethod
    def construct_cmds(cls):
        return '\n'.join([
            'b {loc}'.format(loc=cls.location),
            PROCESS_RUN,
            'n',
            LOAD_EXTENSION,
            cls.extension_cmds.strip(),
            'q',
        ])

    @classmethod
    def setUpClass(cls):
        cmd_file = persist(cls.construct_cmds())
        script_file = persist(cls.lua_script)
        process_cmd = [
            DEBUGGER,
            RUN_CMD_FILE,
            cmd_file.name,
            INFERIOR_ARGS,
            LUAJIT_BINARY,
            script_file.name,
        ]
        cls.output = filter_debugger_output(execute_process(process_cmd))
        cmd_file.close()
        script_file.close()

    def check(self):
        if LEGACY:
            self.assertRegexpMatches(self.output, self.pattern.strip())
        else:
            self.assertRegex(self.output, self.pattern.strip())


class TestLoad(TestCaseBase):
    extension_cmds = ''
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        'lj-tv command intialized\n'
        'lj-state command intialized\n'
        'lj-arch command intialized\n'
        'lj-gc command intialized\n'
        'lj-str command intialized\n'
        'lj-tab command intialized\n'
        'lj-stack command intialized\n'
        'LuaJIT debug extension is successfully loaded\n'
    )


class TestLJArch(TestCaseBase):
    extension_cmds = 'lj-arch'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        'LJ_64: (True|False), '
        'LJ_GC64: (True|False), '
        'LJ_DUALNUM: (True|False)'
    )


class TestLJState(TestCaseBase):
    extension_cmds = 'lj-state'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        'VM state: [A-Z]+\n'
        'GC state: [A-Z]+\n'
        'JIT state: [A-Z]+\n'
    )


class TestLJGC(TestCaseBase):
    extension_cmds = 'lj-gc'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        'GC stats: [A-Z]+\n'
        '\ttotal: \d+\n'
        '\tthreshold: \d+\n'
        '\tdebt: \d+\n'
        '\testimate: \d+\n'
        '\tstepmul: \d+\n'
        '\tpause: \d+\n'
        '\tsweepstr: \d+/\d+\n'
        '\troot: \d+ objects\n'
        '\tgray: \d+ objects\n'
        '\tgrayagain: \d+ objects\n'
        '\tweak: \d+ objects\n'
        '\tmmudata: \d+ objects\n'
    )


class TestLJStack(TestCaseBase):
    extension_cmds = 'lj-stack'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        '-+ Red zone:\s+\d+ slots -+\n'
        '(0x[a-zA-Z0-9]+\s+\[(S|\s)(B|\s)(T|\s)(M|\s)\] VALUE: nil\n?)*\n'
        '-+ Stack:\s+\d+ slots -+\n'
        '(0x[A-Za-z0-9]+(:0x[A-Za-z0-9]+)?\s+'
        '\[(S|\s)(B|\s)(T|\s)(M|\s)\].*\n?)+\n'
    )


class TestLJTV(TestCaseBase):
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    extension_cmds = (
        'lj-tv L->base\n'
        'lj-tv L->base + 1\n'
        'lj-tv L->base + 2\n'
        'lj-tv L->base + 3\n'
        'lj-tv L->base + 4\n'
        'lj-tv L->base + 5\n'
        'lj-tv L->base + 6\n'
        'lj-tv L->base + 7\n'
        'lj-tv L->base + 8\n'
        'lj-tv L->base + 9\n'
        'lj-tv L->base + 10\n'
        'lj-tv L->base + 11\n'
    )

    lua_script = (
        'local ffi = require("ffi")\n'
        'print(\n'
        '  nil,\n'
        '  false,\n'
        '  true,\n'
        '  "hello",\n'
        '  {1},\n'
        '  1,\n'
        '  1.1,\n'
        '  coroutine.create(function() end),\n'
        '  ffi.new("int*"),\n'
        '  function() end,\n'
        '  print,\n'
        '  require\n'
        ')\n'
    )

    pattern = (
        'nil\n'
        'false\n'
        'true\n'
        'string \"hello\" @ 0x[a-zA-Z0-9]+\n'
        'table @ 0x[a-zA-Z0-9]+ \(asize: \d+, hmask: 0x[a-zA-Z0-9]+\)\n'
        '(number|integer) .*1.*\n'
        'number 1.1\d+\n'
        'thread @ 0x[a-zA-Z0-9]+\n'
        'cdata @ 0x[a-zA-Z0-9]+\n'
        'Lua function @ 0x[a-zA-Z0-9]+, [0-9]+ upvalues, .+:[0-9]+\n'
        'fast function #[0-9]+\n'
        'C function @ 0x[a-zA-Z0-9]+\n'
    )


class TestLJStr(TestCaseBase):
    extension_cmds = 'lj-str fname'
    location = 'lj_cf_dofile'
    lua_script = 'pcall(dofile("name"))'
    pattern = 'String: .* \[\d+ bytes\] with hash 0x[a-zA-Z0-9]+'


class TestLJTab(TestCaseBase):
    extension_cmds = 'lj-tab t'
    location = 'lj_cf_unpack'
    lua_script = 'unpack({1; a = 1})'
    pattern = (
        'Array part: 3 slots\n'
        '0x[a-zA-Z0-9]+: \[0\]: nil\n'
        '0x[a-zA-Z0-9]+: \[1\]: .+ 1\n'
        '0x[a-zA-Z0-9]+: \[2\]: nil\n'
        'Hash part: 2 nodes\n'
        '0x[a-zA-Z0-9]+: { string "a" @ 0x[a-zA-Z0-9]+ } => '
        '{ .+ 1 }; next = 0x0\n'
        '0x[a-zA-Z0-9]+: { nil } => { nil }; next = 0x0\n'
    )


for test_cls in TestCaseBase.__subclasses__():
    test_cls.test = lambda self: self.check()

if __name__ == '__main__':
    unittest.main(verbosity=2)
