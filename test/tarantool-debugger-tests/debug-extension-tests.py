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
RX_BCN = r'00\d\d'
RX_IRN = RX_BCN  # The same as for the bytecodes.
RX_FRAME = r'\[(S|\s)(B|\s)(T|\s)(M|\s)\]'
RX_IRREF = r'0x\d\d\d\d'


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

IS_GC64 = execute_process([
    LUAJIT_BINARY, '-e', "print(require('ffi').abi('gc64'))"
]).strip() == 'true'

# Regexp for pointer type in IR.
RX_P = 'p64' if IS_GC64 else 'p32'

# If it is the guaranteed DUALNUM build (for example, on aarch64),
# we use this regexp for the guaranteed 'integer' check and
# 'number' for single-number build.
RX_INT = r'integer' if IS_DUALNUM else r'number'
RX_ISDUALNUM = r'True' if IS_DUALNUM else r'False'


# Assume not cross-platform debugging.
machine = os.uname().machine
if machine == 'x86_64':
    RX_GPR = r'r\w\w'
    RX_FPR = r'xmm\d+'
elif machine == 'arm64' or machine == 'aarch64':
    RX_GPR = r'x\d+'
    RX_FPR = r'd\d+'
else:
    raise Exception('Unknown architecture in testing')


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


# Test that the emitted debug information supports macro
# definitions.
def check_macro_debug_info():
    cmd_file = persist('\n'.join([
        'b lj_cf_print',
        *PROCESS_RUN,
        'n',
        'p gcval(L->base)',
        'q',
    ]))
    process_cmd = [
        DEBUGGER,
        *RUN_CMD_FILE,
        cmd_file.name,
        INFERIOR_ARGS,
        LUAJIT_BINARY,
        '-e',
        'print("")'
    ]
    output = execute_process(process_cmd)
    cmd_file.close()
    return re.search(r'\(GCobj \*\) ' + RX_ADDR, output) is not None


SUPPORT_MACRO_EXPAND = check_macro_debug_info()


# LLDB + Clang on macOS (for example) can't produce debug info
# for the C-defined macros. Thus, we hardcoded its value manually.
def gcval(arg):
    if SUPPORT_MACRO_EXPAND:
        return 'gcval(' + arg + ')'
    else:
        if IS_GC64:
            LJ_GCVMASK = '(((uint64_t)1 << 47) - 1)'
            return '(((' + arg + ')->gcr).gcptr64 & ' + LJ_GCVMASK + ')'
        else:
            return '((' + arg + ')->gcr).gcptr32'


def mref(arg, tp):
    if SUPPORT_MACRO_EXPAND:
        return 'mref(' + arg + ', ' + tp + ')'
    else:
        if IS_GC64:
            return '((' + tp + '*)(' + arg + ').ptr64)'
        else:
            return '((' + tp + '*)(' + arg + ').ptr32)'


def gcref(arg):
    if SUPPORT_MACRO_EXPAND:
        return 'gcref(' + arg + ')'
    else:
        if IS_GC64:
            return '(' + arg + ').gcptr64'
        else:
            return '(' + arg + ').gcptr32'


class TestLoad(TestCaseBase):
    extension_cmds = ''
    location = 'lj_cf_print'
    lua_script = 'print(1)'
    pattern = (
        r'lj-arch command initialized\n'
        r'lj-bc command initialized\n'
        r'lj-ctype command initialized\n'
        r'lj-func command initialized\n'
        r'lj-gc command initialized\n'
        r'lj-gco command initialized\n'
        r'lj-ir command initialized\n'
        r'lj-jslots command initialized\n'
        r'lj-proto command initialized\n'
        r'lj-stack command initialized\n'
        r'lj-state command initialized\n'
        r'lj-str command initialized\n'
        r'lj-tab command initialized\n'
        r'lj-trace command initialized\n'
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


# Sorted in LJT order.
GCO_ARGS = (
    '"hello",\n'
    'coroutine.create(function() end),\n'
    'function() end,\n'
    'require,\n'
    'print,\n'
    'ffi.new("int*"),\n'
    '{1},\n'
    'newproxy(),\n'
)


GCO_RX = (
    r'string \"hello\" @ ' + RX_ADDR + r'\n'
    r'thread @ ' + RX_ADDR + r'\n'
    r'Lua function @ ' + RX_ADDR + r', [0-9]+ upvalues, .+:[0-9]+\n'
    r'C function @ ' + RX_ADDR + r'\n'
    r'fast function #[0-9]+\n'
    r'cdata @ ' + RX_ADDR + r' \[\d+\] <int \*> 0x0\n'
    r'table @ ' + RX_ADDR + r' \(asize: \d+, hmask: ' + RX_HASH + r'\)\n'
    r'userdata @ ' + RX_ADDR + r'\n'
)


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
        '  debug.upvalueid(print, 1), \n' +  # lightuserdata
        GCO_ARGS +
        '  1,\n'
        '  1.1\n'
        ')\n'
    )

    pattern = (
        r'nil\n'
        r'false\n'
        r'true\n'
        r'light userdata @ ' + RX_ADDR + r'\n' +
        GCO_RX +
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


class TestLJGCo(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'lj-gco ' + gcval('L->base + 0') + '\n'
        'lj-gco ' + gcval('L->base + 1') + '\n'
        'lj-gco ' + gcval('L->base + 2') + '\n'
        'lj-gco ' + gcval('L->base + 3') + '\n'
        'lj-gco ' + gcval('L->base + 4') + '\n'
        'lj-gco ' + gcval('L->base + 5') + '\n'
        'lj-gco ' + gcval('L->base + 6') + '\n'
        'lj-gco ' + gcval('L->base + 7') + '\n'
    )

    lua_script = (
        'local ffi = require("ffi")\n'
        'print(\n' +
        GCO_ARGS +
        '  1\n'  # Stub for the pattern.
        ')\n'
    )

    pattern = GCO_RX


PROTO_FUNC_SCRIPT = (
    'local uvname = false\n'
    'local function testf(...)\n'
    '  local a = ...\n'
    '  local s1 = a + 42\n'
    '  uvname = "conststr"\n'
    '  if a >= 42 then\n'
    '    return a - s1\n'
    '  end\n'
    'end\n'
    'print(testf)\n'
)


PROTO_FUNC_BC_RX = (
    RX_BCN + r' FUNCV  rbase:   \d\s*\n' +
    RX_BCN + r' VARG   base:    \d lit:     \d lit:     \d\s*\n' +
    RX_BCN + r' ADDVN  dst:     \d var:     \d num: +\d' +
             r' ; ' + RX_INT + r' 42\s*\n' +
    RX_BCN + r' USETS  uv:      \d str:     \d' +
             r' ; upvalue "uvname" @ ' + RX_ADDR +
             r' ; string "conststr" @ ' + RX_ADDR + r'\s*\n' +
    RX_BCN + r' KSHORT dst:     \d lits:   42\s*\n' +
    RX_BCN + r' ISGT   var:     \d var:     \d\s*\n' +
    RX_BCN + r' JMP    rbase:   \d jump:  => ' + RX_BCN + r'\s*\n' +
    RX_BCN + r' SUBVV  dst:     \d var:     \d var:     \d\s*\n' +
    RX_BCN + r' RET1   rbase:   \d lit:     \d\s*\n' +
    RX_BCN + r' RET0   rbase:   \d lit:     \d\s*\n'
)


class TestLJFunc(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = 'lj-func ' + gcval('L->base')
    lua_script = PROTO_FUNC_SCRIPT
    pattern = PROTO_FUNC_BC_RX


class TestLJProto(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'lj-proto '
        '  ((char *) ' + mref(
            '((GCfuncL *)' + gcval('L->base') + ')->pc', 'char'
        ) + ') - sizeof(GCproto)\n'
    )
    lua_script = PROTO_FUNC_SCRIPT
    pattern = PROTO_FUNC_BC_RX


class TestLJBC(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'lj-bc ' + mref(
            '((GCfuncL *)' + gcval('L->base') + ')->pc', 'BCIns'
        ) + '\n'
        'lj-bc ' + mref(
            '((GCfuncL *)' + gcval('L->base') + ')->pc', 'BCIns'
        ) + ' + 6\n'
    )
    lua_script = PROTO_FUNC_SCRIPT
    pattern = (
        r'FUNCV  rbase:   \d\s*\n'
        r'JMP    rbase:   \d jump:  \+\d\n'
    )


# JIT engine.


class TestLJTraceBase(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'for _ = 1, 4 do end\n'
        'print()\n'
    )
    pattern = (
        r'Trace 1 start\n'
        r'\t*proto: ' + RX_ADDR + r'\n' +
        r'\t*BC: ' + RX_ADDR + r'\n' +
        r'---- TRACE IR\n' +
        RX_IRN + r'\s+    int SLOAD  \[L \] lit: #[12]   lit: C?I\n' +
        RX_IRN + r'\s+ \+ int ADD    \[C \] ref: ' + RX_IRN +
                 r' ref: integer 1\n' +
        RX_IRN + r'\s+ >  int LE     \[N \] ref: ' + RX_IRN +
                 r' ref: integer 4\n' +
        RX_IRN + r'\s+ >  --- LOOP   \[S \]\s*\n' +
        RX_IRN + r'\s+ \+ int ADD    \[C \] ref: ' + RX_IRN +
                 r' ref: integer 1\n' +
        RX_IRN + r'\s+ >  int LE     \[N \] ref: ' + RX_IRN +
                 r' ref: integer 4\n' +
        RX_IRN + r'\s+    int PHI    \[S \] ref: ' + RX_IRN + r' ref: ' +
                 RX_IRN + r'\n' +
        RX_IRN + r'\s+        NOP    \[N \]\s*\n'
    )


# Check the IR enumeration correcness by test the lowest (LT) and
# the highest (CARG) IRs. Also, checks CALL* occasionally.
class TestLJTraceIRRange(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'ffi.cdef[[int getpid(int, int);]]\n'  # Use argument for testing.
        'jit.opt.start("hotloop=1")\n'
        'for i = 1, 4 do\n'
        '  if i < 100 then\n'  # LT.
        '    ffi.C.getpid(i, 1LL)\n'  # CARG and CALLXS.
        '  end\n'
        'end\n'
        'print()\n'
    )
    # IRs from variant part of the trace.
    pattern = (
        RX_IRN + r'\s+ >  int LT     \[N \] ref: ' +
                 RX_IRN + r' ref: integer 100\n' +
        RX_IRN + r'\s+    nil CARG   \[N \] ref: ' +
                 RX_IRN + r' ref: integer 1\n' +
        RX_IRN + r'\s+    int CALLXS \[S \] \[' + RX_ADDR +
                 r'\]\(\{' + RX_IRN + r'\}, \{integer 1\}\)'
    )


# Test /rs flags.
class TestLJTraceFlags(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace /rs ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'local r = 0.1\n'
        'for i = 1, 4 do\n'
        '  r = i + r\n'
        'end\n'
        'print()\n'
    )
    # IRs and snapshot from variant part of the trace.
    pattern = (
        RX_IRN + r'\s+' + RX_FPR + r'\s* \+ num ADD.*\n' +
        RX_IRN + r'\s+' + RX_GPR + r'\s* \+ int ADD.*\n' +
        r'\.\.\.\.\s* SNAP   #\d   \[ (---- )*' + RX_IRN + r' \]'
    )


class TestLJIRConst(TestCaseBase):
    location = 'trace_stop'

    # No narrowing of 42.
    if IS_DUALNUM:
        # KNUM occupies 2 slots.
        _knum_irnum = '6'
        _kgc_irnum = '8' if IS_GC64 else '7'
        _kptr_irnum = '10' if IS_GC64 else '8'
    else:
        # KNUM occupies 2 slots.
        _knum_irnum = '8'
        _kgc_irnum = '10' if IS_GC64 else '9'
        _kptr_irnum = '12' if IS_GC64 else '10'
    extension_cmds = (
        'n\n'  # Load J.
        'lj-ir &J->cur.ir[0x8000 - 0]\n'
        'lj-ir &J->cur.ir[0x8000 - 1]\n'
        'lj-ir &J->cur.ir[0x8000 - 2]\n'
        'lj-ir &J->cur.ir[0x8000 - 3]\n'
        'lj-ir &J->cur.ir[0x8000 - 4]\n'
        # Skip non-DUALNUM narrowed value.
        'lj-ir &J->cur.ir[0x8000 - ' + _knum_irnum + ']\n'
        'lj-ir &J->cur.ir[0x8000 - ' + _kgc_irnum + ']\n'
        'lj-ir &J->cur.ir[0x8000 - ' + _kptr_irnum + ']\n'
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'local function trace(x)\n'
        '   return x + 42, x + 0.5, x .. "1"\n'
        'end\n'
        'trace(1)\n'
        'trace(1)\n'
    )
    pattern = (
        RX_P + r' BASE.*\n' +
        r'\s* nil KPRI.*\n'
        r'\s* fal KPRI.*\n'
        r'\s* tru KPRI.*\n'
        r'\s* int KINT.*cst: integer 42\s*\n'
        r'\s* num KNUM.*cst: number 0.5\s*\n'
        r'\s* str KGC.*cst: string "1".*\n' +
        r'\s*' + RX_P + r' KPTR.*cst: \[' + RX_ADDR + r'\]'
    )


class TestLJIRFloadNeg(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'local function trace(a)\n'
        '  local x = -a\n'
        '  return x\n'
        'end\n'
        'trace(1.1)\n'
        'trace(1.1)\n'
        'print()\n'
    )
    pattern = (
        r'num FLOAD .* ref: nil  lit: offsetof\(GG, J\.ksimd\[LJ_KSIMD_NEG\]\)'
    )


class TestLJIRFloadAbs(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'local math_abs = math.abs\n'
        'local function trace(a)\n'
        '  local x = math_abs(a)\n'
        '  return x\n'
        'end\n'
        'trace(1)\n'
        'trace(1)\n'
        'print()\n'
    )
    pattern = (
        r'num FLOAD .* ref: nil  lit: offsetof\(GG, J\.ksimd\[LJ_KSIMD_ABS\]\)'
    )


# XXX: Implemented only for GC64 in LuaJIT until backporting the
# corresponding commit.
if IS_GC64:
    class TestLJIRFloadGCRootBaseMT(TestCaseBase):
        location = 'lj_cf_print'
        extension_cmds = (
            'n\n'  # Load L.
            'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
        )
        lua_script = (
            'jit.opt.start("hotloop=1")\n'
            'local function trace(a)\n'
            'local x = a.sub(1, 2)\n'
            '  return x\n'
            'end\n'
            'trace("12")\n'
            'trace("12")\n'
            'print()\n'
        )
        pattern = (
            r'tab FLOAD .* ref: nil  lit: '
            r'offsetof\(GG, g\.gcroot\[GCROOT_BASEMT_STR\]\.gcptr64\)'
        )

    class TestLJIRFloadGCRootIO(TestCaseBase):
        location = 'lj_cf_print'
        extension_cmds = (
            'n\n'  # Load L.
            'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
        )
        lua_script = (
            'jit.opt.start("hotloop=1")\n'
            'local io_flush = io.flush\n'
            'local function trace()\n'
            '  io_flush()\n'
            'end\n'
            'trace()\n'
            'trace()\n'
            'print()\n'
        )
        pattern = (
            r'udt FLOAD .* ref: nil  lit: '
            r'offsetof\(GG, g\.gcroot\[GCROOT_IO_OUTPUT\]\.gcptr64\)'
        )


# Some IRs related to tables.
class TestLJIRTable(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'local function trace(t)\n'
        '  t.a = nil\n'
        '  t.b = 1\n'
        '  return t\n'
        'end\n'
        'trace({a = 1})\n'
        'trace({a = 1})\n'
        'print()\n'
    )
    pattern = (
        r'(?s)int FLOAD .* tab\.hmask\n'
        r'.*' + RX_P + r' FLOAD .* tab\.node\n'
        r'.*' + RX_P + r' HREFK .* string "a" @ ' + RX_ADDR +
                       r' KSLOT: @\d\n'
        r'.*' + RX_P + r' HREF .* string "b" @ ' + RX_ADDR + r'\s*\n'
        r'.*' + RX_P + r' EQ .* \[g->nilnode\]'
    )


class TestLJIRUref(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'local uv = 0\n'
        'local function trace(a)\n'
        '  uv = a\n'
        '  return uv\n'
        'end\n'
        'trace(1)\n'
        'trace(1)\n'
        'print()\n'
    )
    pattern = r'UREFO .* lit: #0'


# Check border values (that always avalable) of CALL IRs.
class TestLJIRCall(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'jit.opt.start("hotloop=1")\n'
        'local function trace(a, b)\n'
        '  return a < b, ffi.errno()\n'
        'end\n'
        'trace("abc", "abd")\n'
        'trace("abc", "abd")\n'
        'print(1)\n'
    )
    pattern = (
        r'(?s)int CALLN .* '
        r'lj_str_cmp\(\{' + RX_IRN + r'\}, \{' + RX_IRN + r'\}\)'
        r'.*int CALLS .* lj_vm_errno\(\)'
    )


# Test ffi call with ctype stored in CARG.
class TestLJIRCallXSCType(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-trace ' + gcref('((GG_State *)L)->J->trace[1]')
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'ffi.cdef[[int printf(const char *fmt, ...);]]\n'
        'jit.opt.start("hotloop=1")\n'
        'local function trace()\n'
        '  local t = ffi.C.printf("")\n'
        '  return t\n'
        'end\n'
        'trace()\n'
        'trace()\n'
        'print()\n'
    )
    pattern = (
        r'int CALLXS .* [' + RX_ADDR + r'\]\(.*\) ctype: \[\d+\] <int \(\)>'
    )


class TestLJJSlotsBase(TestCaseBase):
    location = 'trace_stop'
    extension_cmds = (
        'n\n'  # Load J.
        'lj-jslots J->L\n'
    )
    lua_script = (
        'jit.opt.start("hotloop=1")\n'
        'for _ = 1, 4 do end\n'
    )
    pattern = (
        r'(?s)(.*' +
        RX_ADDR + ' ' + RX_IRN + r' (B|\s) \[(F|\s)(C|\s)\] \w\w\w ' +
        RX_IRREF +
        r'.*)+'
    )


def cdata_rx(tpstr, suffix=None):
    return r'cdata @ ' + RX_ADDR + r' \[\d+\] <' + tpstr + '> ' + (
        RX_ADDR if not suffix else suffix
    )


CHAR_SIGNED = machine in ['arm64', 'aarch64'] and sys.platform != 'darwin'
HAS_LONG_DOUBLE = not (machine in ['arm64', 'aarch64'] and
                       sys.platform == 'darwin')


class TestLJCTypePrim(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
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
        'lj-tv L->base + 14\n'
        'lj-tv L->base + 15\n'
        'lj-tv L->base + 16\n'
        'lj-tv L->base + 17\n'
        'lj-tv L->base + 18\n'
        'lj-tv L->base + 19\n'
        'lj-tv L->base + 20\n'
        'lj-tv L->base + 21\n'
        'lj-tv L->base + 22\n'
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'print(\n'
        '  ffi.new("bool"),\n'
        '  ffi.new("char"),\n'
        '  ffi.new("signed char"),\n'
        '  ffi.new("unsigned char"),\n'
        '  ffi.new("int"),\n'
        '  ffi.new("short"),\n'
        '  ffi.new("unsigned"),\n'
        '  ffi.new("int8_t"),\n'
        '  ffi.new("int16_t"),\n'
        '  ffi.new("int32_t"),\n'
        '  ffi.new("int64_t"),\n'
        '  ffi.new("uint8_t"),\n'
        '  ffi.new("uint64_t"),\n'
        '  ffi.new("float"),\n'
        '  ffi.new("double"),\n'
        '  ffi.new("long double"),\n'
        '  1i,\n'
        '  ffi.new("complex float", 1, -2),\n'
        '  ffi.new("const volatile int"),\n'
        '  ffi.new("void *"),\n'
        '  ffi.new("void * __ptr32"),\n'
        '  ffi.new("int &"),\n'
        '  ffi.typeof(1LL)\n'
        ')\n'
    )
    pattern = (
        cdata_rx('bool') + r'\n' +
        cdata_rx('char') + r'\n' +
        cdata_rx(('signed ' if CHAR_SIGNED else '') + 'char') + r'\n' +
        cdata_rx(('unsigned ' if not CHAR_SIGNED else '') + 'char') + r'\n' +
        cdata_rx('int') + r'\n' +
        cdata_rx('short') + r'\n' +
        cdata_rx('unsigned int') + r'\n' +
        cdata_rx(('signed ' if CHAR_SIGNED else '') + 'char') + r'\n' +
        cdata_rx('short') + r'\n' +
        cdata_rx('int') + r'\n' +
        cdata_rx('int64_t', '0LL') + r'\n' +
        cdata_rx(('unsigned ' if not CHAR_SIGNED else '') + 'char') + r'\n' +
        cdata_rx('uint64_t', '0ULL') + r'\n' +
        cdata_rx('float') + r'\n' +
        cdata_rx('double') + r'\n' +
        cdata_rx(('long ' if HAS_LONG_DOUBLE else '') + 'double') + r'\n' +
        cdata_rx('complex', r'0\+1i') + r'\n' +
        cdata_rx('complex float', '1-2i') + r'\n' +
        cdata_rx('const volatile int') + r'\n' +
        cdata_rx(r'void \*') + r'\n' +
        cdata_rx(r'void \* __ptr32') + r'\n' +
        cdata_rx('int &') + r'\n' +
        cdata_rx('ctype') + r'\n'
    )


class TestLJCTypeStructUnionEnum(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-tv L->base\n'
        'lj-tv L->base + 1\n'
        'lj-tv L->base + 2\n'
        'lj-tv L->base + 3\n'
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'ffi.cdef[[\n'
        '  struct test {int a;};\n'
        ']]\n'
        'print(\n'
        '  ffi.new("struct test"),\n'
        '  ffi.new("struct {int a;}"),\n'
        '  ffi.new("union {int a;}"),\n'
        '  ffi.new("enum {ENUM1}")\n'
        ')\n'
    )
    pattern = (
        cdata_rx('struct test') + r'\n' +
        cdata_rx(r'struct \d+') + r'\n' +
        cdata_rx(r'union \d+') + r'\n' +
        cdata_rx(r'enum \d+') + r'\n'
    )


class TestLJCTypeArray(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-tv L->base\n'
        'lj-tv L->base + 1\n'
        'lj-tv L->base + 2\n'
        'lj-tv L->base + 3\n'
        'lj-tv L->base + 4\n'
        'lj-tv L->base + 5\n'
        'lj-tv L->base + 6\n'
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'print(\n'
        '  ffi.new("char [0]"),\n'
        '  ffi.new("int [1]"),\n'
        '  ffi.new("complex [2]"),\n'
        '  ffi.new("complex float [3]"),\n'
        '  ffi.new("float __attribute__((vector_size(4)))"),\n'
        '  ffi.new("int (&)[5]"),\n'
        '  ffi.new("int[?]", 6)\n'
        ')\n'
    )
    pattern = (
        cdata_rx(r'char \[0\]') + r'\n' +
        cdata_rx(r'int \[1\]') + r'\n' +
        cdata_rx(r'complex \[2\]') + r'\n' +
        cdata_rx(r'complex float \[3\]') + r'\n' +
        cdata_rx(r'float __attribute__\(\(vector_size\(4\)\)\)') + r'\n' +
        cdata_rx(r'int \(&\)\[5\]') + r'\n' +
        cdata_rx(r'int \[\?\]') + r'\n'
    )


class TestLJCTypeFunc(TestCaseBase):
    location = 'lj_cf_print'
    extension_cmds = (
        'n\n'  # Load L.
        'lj-tv L->base\n'
        'lj-tv L->base + 1\n'
        'lj-tv L->base + 2\n'
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'ffi.cdef[[void getpid(void);]]\n'
        'print(\n'
        '  ffi.C.getpid,\n'
        '  ffi.new("int (*)()"),\n'
        '  ffi.new("int (*(*)(void))[2]")\n'
        ')\n'
    )
    pattern = (
        cdata_rx(r'void \(\)') + r'\n' +
        cdata_rx(r'int \(\*\)\(\)') + r'\n' +
        cdata_rx(r'int \(\* \(\*\)\(\)\)\[2\]') + r'\n'
    )


class TestLJCTypeBase(TestCaseBase):
    location = 'lj_cf_ffi_new'
    extension_cmds = (
        # Load `ct`. Skip inlined functions for LLDB. The skip is
        # harmless for GDB since we are still in the body of the
        # function.
        'n\n'
        'n\n'
        'n\n'
        'n\n'
        'n\n'
        'n\n'
        'lj-ctype ct\n'
    )
    lua_script = (
        'local ffi = require("ffi")\n'
        'ffi.new("int")\n'
    )
    pattern = r'\[\d+\] <int>'


for test_cls in TestCaseBase.__subclasses__():
    test_cls.test = lambda self: self.check()

if __name__ == '__main__':
    unittest.main(verbosity=2)
