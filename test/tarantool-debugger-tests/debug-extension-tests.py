# This file provides tests for LuaJIT debug extensions for lldb
# and gdb.

import os
import re
import subprocess
import sys
import tempfile
import unittest

from threading import Timer

LEGACY = re.match(r'^2\.', sys.version)

LUAJIT_BINARY = os.environ['LUAJIT_TEST_BINARY']
EXTENSION_PATH = os.environ['DEBUGGER_EXTENSION_PATH']
DEBUGGER = os.environ['DEBUGGER_COMMAND']
LLDB = 'lldb' in DEBUGGER
EXTENSION = EXTENSION_PATH + '/luajit_dbg.py'
TIMEOUT = 10

if LLDB:
    INFERIOR_ARGS = '--'
    LOAD_EXTENSION = 'command script import ' + EXTENSION
    PROCESS_RUN = (
        # Prevent errors in case when running tests in Docker.
        'settings set target.disable-aslr false\n'
        'process launch'
    )
    # Don't run any initialization scripts.
    RUN_CMD_FILE = [
        '--batch',
        '--no-lldbinit',
        '--no-use-colors',
        '--source-quietly',
        '--source'
    ]
else:
    # GDB.
    INFERIOR_ARGS = '--args'
    LOAD_EXTENSION = 'source ' + EXTENSION
    PROCESS_RUN = 'run'
    # Don't run any initialization scripts.
    RUN_CMD_FILE = ['--batch', '--nx', '--quiet', '--command']

RX_ADDR = r'0x[a-f0-9]+'
RX_HASH = RX_ADDR  # The same pattern for hexademic values.
RX_FRAME = r'\[(S|\s)(B|\s)(T|\s)(M|\s)\]'


def persist(data):
    tmp = tempfile.NamedTemporaryFile(mode='w')
    tmp.write(data)
    tmp.flush()
    return tmp


def execute_process(cmd, timeout=TIMEOUT):
    if LEGACY:
        # XXX: The Python 2.7 version of `subprocess.Popen`
        # doesn't have a timeout option, so the required
        # functionality was implemented via `threading.Timer`.
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # This prevents sending of SIGSTTOU to the test when
            # running by `make'. Stdin is unused anyway.
            stdin=subprocess.DEVNULL
        )
        timer = Timer(TIMEOUT, process.kill)
        timer.start()
        stdout, _ = process.communicate()
        timer.cancel()

        # XXX: If the timeout is exceeded and the process is
        # killed by the timer, then the return code is non-zero,
        # and we are going to blow up.
        assert process.returncode == 0
        return stdout.decode('ascii')
    else:
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # This prevents sending of SIGSTTOU to the test when
            # running by `make'. Stdin is unused anyway.
            stdin=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=TIMEOUT
        )
        return process.stdout


IS_DUALNUM = execute_process([
    LUAJIT_BINARY, '-e', "print(require('ffi').abi('dualnum'))"
]).strip() == 'true'

# If it is the guaranteed DUALNUM build (for example, on aarch64),
# we use this regexp for the guaranteed 'integer' check and
# 'number' for single-number build.
RX_INT = r'integer' if IS_DUALNUM else r'number'
RX_ISDUALNUM = r'True' if IS_DUALNUM else r'False'


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
            *RUN_CMD_FILE,
            cmd_file.name,
            INFERIOR_ARGS,
            LUAJIT_BINARY,
            script_file.name,
        ]
        cls.output = execute_process(process_cmd)
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
        r'lj-arch command initialized\n'
        r'lj-gc command initialized\n'
        r'lj-stack command initialized\n'
        r'lj-state command initialized\n'
        r'lj-str command initialized\n'
        r'lj-tab command initialized\n'
        r'lj-tv command initialized\n'
        r'LuaJIT debug extension is successfully loaded'
    )


class TestLJArch(TestCaseBase):
    extension_cmds = 'lj-arch'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        r'LJ_64: (True|False), '
        r'LJ_GC64: (True|False), '
        r'LJ_DUALNUM: ' + RX_ISDUALNUM
    )


class TestLJState(TestCaseBase):
    extension_cmds = 'lj-state'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        r'VM state: [A-Z]+\n'
        r'GC state: [A-Z]+\n'
        r'JIT state: [A-Z]+\n'
    )


class TestLJGC(TestCaseBase):
    extension_cmds = 'lj-gc'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        r'GC stats: [A-Z]+\n'
        r'\ttotal: \d+\n'
        r'\tthreshold: \d+\n'
        r'\tdebt: \d+\n'
        r'\testimate: \d+\n'
        r'\tstepmul: \d+\n'
        r'\tpause: \d+\n'
        r'\tsweepstr: \d+/\d+\n'
        r'\troot: \d+ objects\n'
        r'\tgray: \d+ objects\n'
        r'\tgrayagain: \d+ objects\n'
        r'\tweak: \d+ objects\n'
        r'\tmmudata: \d+ objects\n'
    )


STACK_RX = (
    r'-+ Red zone:\s+\d+ slots -+\n'
    r'(' + RX_ADDR + r'\s+' + RX_FRAME + r' VALUE: nil\n?)*\n'
    r'-+ Stack:\s+\d+ slots -+\n'
    r'(' + RX_ADDR + r'(:' + RX_ADDR + r')?\s+' + RX_FRAME + r'.*\n?)+\n'
)


class TestLJStackBase(TestCaseBase):
    extension_cmds = 'lj-stack'
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = STACK_RX


# Check LLDB correctness for the specific stack.
class TestLJStackFunc(TestCaseBase):
    extension_cmds = 'lj-stack'
    location = 'lj_cf_print'
    lua_script = (
        'local function nop() end\n'
        'print()\n'
    )
    pattern = STACK_RX


class TestLJTV(TestCaseBase):
    location = 'lj_cf_print'
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
        'lj-tv L->base + 12\n'
        'lj-tv L->base + 13\n'
    )

    # Sorted in LJT order.
    lua_script = (
        'local ffi = require("ffi")\n'
        'print(\n'
        '  nil,\n'
        '  false,\n'
        '  true,\n'
        '  debug.upvalueid(print, 1), \n'  # lightuserdata
        '  "hello",\n'
        '  coroutine.create(function() end),\n'
        '  function() end,\n'
        '  require,\n'
        '  print,\n'
        '  ffi.new("int*"),\n'
        '  {1},\n'
        '  newproxy(),\n'
        '  1,\n'
        '  1.1\n'
        ')\n'
    )

    pattern = (
        r'nil\n'
        r'false\n'
        r'true\n'
        r'light userdata @ ' + RX_ADDR + r'\n'
        r'string \"hello\" @ ' + RX_ADDR + r'\n'
        r'thread @ ' + RX_ADDR + r'\n'
        r'Lua function @ ' + RX_ADDR + r', [0-9]+ upvalues, .+:[0-9]+\n'
        r'C function @ ' + RX_ADDR + r'\n'
        r'fast function #[0-9]+\n'
        r'cdata @ ' + RX_ADDR + r'\n'
        r'table @ ' + RX_ADDR + r' \(asize: \d+, hmask: ' + RX_HASH + r'\)\n'
        r'userdata @ ' + RX_ADDR + r'\n'
        RX_INT + r' .*1.*\n'
        r'number 1.1\d+\n'
    )


class TestLJStr(TestCaseBase):
    extension_cmds = (
        # XXX: Get the value to the stack slot for the variable.
        'n\n'
        'lj-str fname\n'
    )
    location = 'lj_cf_dofile'
    lua_script = 'pcall(dofile("name"))'
    pattern = r'String: .* \[\d+ bytes\] with hash ' + RX_HASH


class TestLJTab(TestCaseBase):
    extension_cmds = (
        # XXX: Get the value to the stack slot for the variable.
        'n\n'
        'lj-tab t\n'
    )
    location = 'lj_cf_unpack'
    lua_script = 'unpack({1; a = 1})'
    pattern = (
        r'Array part: 3 slots\n' +
        RX_ADDR + r': \[0\]: nil\n' +
        RX_ADDR + r': \[1\]: .+ 1\n' +
        RX_ADDR + r': \[2\]: nil\n' +
        r'Hash part: 2 nodes\n' +
        RX_ADDR + r': { string "a" @ ' + RX_ADDR + r' } => ' +
        r'{ .+ 1 }; next = 0x0\n' +
        RX_ADDR + r': { nil } => { nil }; next = 0x0\n'
    )


for test_cls in TestCaseBase.__subclasses__():
    test_cls.test = lambda self: self.check()

if __name__ == '__main__':
    unittest.main(verbosity=2)
