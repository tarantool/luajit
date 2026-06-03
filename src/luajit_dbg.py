# Debug extension for LuaJIT post-mortem analysis.
# To use in GDB:
# `source <path-to-repo>/src/luajit_dbg.py'
# To use in LLDB:
# `command script import <path-to-repo>/src/luajit_dbg.py'

import abc
import re
import struct
import sys

from importlib import import_module

# Make the script compatible with ancient Python.
LEGACY = re.match(r'^2\.', sys.version)

if LEGACY:
    int = long  # noqa: F821
    range = xrange  # noqa: F821


# Debugger. ######################################################


lldb = None
gdb = None

# XXX: While the `gdb` library is only available inside a debug
# session, the `lldb` library can be loaded in any Python script.
# To address that, we need to perform an additional check to
# ensure a debug session is actually running.
debuggers = {
    'gdb': lambda lib: True,
    'lldb': lambda lib: lib.debugger is not None,
}
for name, healthcheck in debuggers.items():
    lib = None
    try:
        lib = import_module(name)
        if healthcheck(lib):
            globals()[name] = lib
            break
    except Exception:
        continue

assert (not not lldb) != (not not gdb), 'Debugger must be either LLDB or GDB.'


class Debugger(object):
    def __init__(self):
        self.dbgtype_cache = {}

    def __new__(self):
        if gdb:
            self.GDB = True
            return super(Debugger, self).__new__(_GDBDebugger)
        elif lldb:
            self.LLDB = True
            return super(Debugger, self).__new__(_LLDBDebugger)

    def configure(self):
        global PADDING, LJ_TISNUM
        if not self.check_libluajit():
            return False
        try:
            self.init_luajit_arch()
            PADDING = ' ' * len(':' + hex((1 << (47 if LJ_GC64 else 32)) - 1))
            LJ_TISNUM = 0xfffeffff if LJ_64 and not LJ_GC64 else LJ_T['NUMX']
        except Exception:
            self.write('luajit_dbg.py failed to load: '
                       'no debugging symbols found for libluajit\n')
            return False
        return True

    def initialize_extension(self, commands):
        if self.configure():
            for name, command in commands.items():
                self.register_command(command, name)
                self.write('{} command initialized\n'.format(name))
            self.write('LuaJIT debug extension is successfully loaded\n')

    @abc.abstractmethod
    def cast(self, typestr, val):
        '''Cast the value to the required C type.'''
        pass

    @abc.abstractmethod
    def sizeof(self, typestr):
        '''Return the size of the given type in bytes.'''
        pass

    @abc.abstractmethod
    def offsetof(self, typestr, fieldstr):
        '''Return the offset of the given field in the type in bytes.'''
        pass

    @abc.abstractmethod
    def cstr(self, strptr):
        '''Return the content of the string by the given pointer.'''
        pass

    @abc.abstractmethod
    def lookup_global(self, symbol):
        '''Look up the global C symbol by the given name.'''
        pass

    @abc.abstractmethod
    def eval(self, command):
        '''Parse and evaluate the given debugger command.'''
        pass

    @abc.abstractmethod
    def write(self, msg):
        '''Print the message.'''
        pass

    @abc.abstractmethod
    def check_libluajit(self):
        '''Check that libluajit is loaded.
        Check that the object file with libluajit symbols is loaded.
        Postpone loading of the extension if needed.
        '''
        pass

    @abc.abstractmethod
    def init_luajit_arch(self):
        '''Initialize LuaJIT architecture-specific globals.
        Initialize build-dependent global constants.
        If no debugging symbols are found raise an error.
        '''
        pass

    @abc.abstractmethod
    def register_command(self, command, name):
        '''Register the command with the corresponding name.'''
        pass

    @abc.abstractproperty
    def LJBase(self):
        '''Base command class.
        Provides the base class for the extension commands.
        '''


class _GDBDebugger(Debugger):
    def _dbgtype(self, typestr):
        if typestr in self.dbgtype_cache:
            return self.dbgtype_cache[typestr]

        m = re.match(r'((?:(?:struct|union) )?\S*)\s*[*]', typestr)

        dbgtype = gdb.lookup_type(typestr) if m is None \
            else gdb.lookup_type(m.group(1)).pointer()

        self.dbgtype_cache[typestr] = dbgtype
        return dbgtype

    def __init__(self):
        super(_GDBDebugger, self).__init__()
        self.CONNECTED = False

    def cast(self, typestr, val):
        return gdb.Value(val).cast(self._dbgtype(typestr))

    def sizeof(self, typestr):
        return self._dbgtype(typestr).sizeof

    def offsetof(self, typestr, fieldstr):
        return int(self._dbgtype(typestr)[fieldstr].bitpos / 8)

    def cstr(self, strptr):
        # A string is printed with a pointer to it. Just strip it.
        return re.sub(r'^0x[a-f0-9]+\s+(?=")', '', str(strptr))

    def lookup_global(self, symbol):
        variable, _ = gdb.lookup_symbol(symbol)
        return variable.value() if variable else None

    def eval(self, command):
        if not command:
            return None

        ret = gdb.parse_and_eval(command)
        if not ret:
            raise gdb.GdbError('table argument empty')
        return ret

    def write(self, msg):
        gdb.write(msg)

    def check_libluajit(self):
        # XXX Fragile: Though connecting the callback looks bad,
        # it respects both Python 2 and Python 3 (see #4828).
        def connect(callback):
            if LEGACY:
                self.CONNECTED = True
            gdb.events.new_objfile.connect(callback)

        # XXX Fragile: Though disconnecting the callback looks
        # bad, it respects both Python 2 and Python 3 (see #4828).
        def disconnect(callback):
            if LEGACY:
                if not self.CONNECTED:
                    return
                self.CONNECTED = False
            gdb.events.new_objfile.disconnect(callback)

        try:
            # Try to remove the callback at first to not append
            # duplicates to gdb.events.new_objfile internal list.
            disconnect(load)
        except Exception:
            # Callback is not connected.
            pass

        try:
            # Detect whether libluajit objfile is loaded.
            gdb.parse_and_eval('luaJIT_setmode')
        except Exception:
            gdb.write('luajit_dbg.py initialization is postponed '
                      'until libluajit objfile is loaded\n')
            # Add a callback to be executed when the next objfile
            # is loaded.
            connect(load)
            return False
        return True

    def init_luajit_arch(self):
        global LJ_64, LJ_DUALNUM, LJ_FR2, LJ_GC64
        LJ_64 = str(gdb.parse_and_eval('IRT_PTR')) == 'IRT_P64'
        LJ_DUALNUM = gdb.lookup_global_symbol('lj_lib_checknumber') is not None
        LJ_FR2 = LJ_GC64 = str(gdb.parse_and_eval('IRT_PGC')) == 'IRT_P64'

    def register_command(self, command, name):
        command(name)

    class LJBase(gdb and gdb.Command or object):
        def __init__(ljbase, name):
            # XXX Fragile: Though the command initialization looks
            # bad, it respects both Python 2 and Python 3.
            gdb.Command.__init__(ljbase, name, gdb.COMMAND_DATA)

        def invoke(ljbase, args, from_tty):
            return ljbase.execute(args)

        @abc.abstractmethod
        def execute(ljbase, args):
            '''Implementation of the command.
            Subclasses override this method to implement the logic of a given
            command, e.g. printing a stack.
            '''

    LJBase = LJBase


class _LLDBDebugger(Debugger):
    def _lldb_tp_isfp(self, tp):
        return tp.GetCanonicalType().GetBasicType() in [
            lldb.eBasicTypeFloat,
            lldb.eBasicTypeDouble,
            lldb.eBasicTypeLongDouble
        ]

    def _lldb_tp_issigned(self, tp):
        return tp.GetCanonicalType().GetBasicType() in [
            lldb.eBasicTypeChar,
            lldb.eBasicTypeSignedChar,
            lldb.eBasicTypeShort,
            lldb.eBasicTypeInt,
            lldb.eBasicTypeLong,
            lldb.eBasicTypeLongLong,
            lldb.eBasicTypeInt128
        ]

    def _lldb_value_from_raw(self, raw_value, size, tp):
        isfp = self._lldb_tp_isfp(tp)
        if isfp:
            pack_flag = '<d'
        elif self._lldb_tp_issigned(tp):
            pack_flag = '<q'
        else:
            pack_flag = '<Q'
        raw_data = struct.pack(pack_flag, raw_value)
        sbdata = lldb.SBData()
        sbdata.SetData(
            lldb.SBError(),
            raw_data,
            lldb.eByteOrderLittle,
            size
        )
        sbval_res = self.target.CreateValueFromData(
            # XXX: Name is required, let's make it meaningful.
            '({tp}){val}'.format(
                tp=tp.name,
                val=raw_value if isfp else hex(raw_value)
            ),
            sbdata,
            tp
        )
        return lldb.value(sbval_res)

    def __init__(self):
        def lldb__add__(lldbval, other):
            other = int(other)
            sbvalue = lldbval.sbvalue
            if sbvalue.TypeIsPointerType():
                tp = sbvalue.GetType()
                sz = sbvalue.deref.size
                addr = sbvalue.GetValueAsUnsigned() + other * sz
                return self._lldb_value_from_raw(
                    addr, sbvalue.GetByteSize(), tp
                )
            else:
                return int(lldbval) + other

        def lldb__bool__(lldbval):
            return int(lldbval) != 0

        def lldb__ge__(lldbval, other):
            return int(lldbval) >= int(other)

        def lldb__getitem__(lldbval, key):
            if type(key) is lldb.value:
                key = int(key)
            if type(key) is int:
                # Allow array access.
                if key >= 0:
                    return lldb.value(
                        lldbval.sbvalue.GetValueForExpressionPath('[%i]' % key)
                    )
                else:
                    # GetValueForExpressionPath doesn't work for
                    # negative offsets.
                    sbvalue = lldbval.sbvalue
                    assert sbvalue.TypeIsPointerType(), \
                        'attempt to get index of non-pointer type'
                    tp = sbvalue.GetType().GetPointeeType()
                    sz = sbvalue.deref.size
                    addr = sbvalue.GetValueAsUnsigned() + key * sz
                    return lldb.value(self.target.CreateValueFromAddress(
                            '({tp}){addr}'.format(tp=tp, addr=addr),
                            lldb.SBAddress(addr, self.target),
                            tp,
                    ))
            elif type(key) is str:
                return lldb.value(lldbval.sbvalue.GetChildMemberWithName(key))
            raise Exception(TypeError('No item of type %s' % str(type(key))))

        def lldb__gt__(lldbval, other):
            return int(lldbval) > int(other)

        def lldb__le__(lldbval, other):
            return int(lldbval) <= int(other)

        def lldb__lt__(lldbval, other):
            return int(lldbval) < int(other)

        def lldb__str__(lldbval):
            # Instead of default GetSummary.
            if not lldbval.sbvalue.TypeIsPointerType():
                tp = lldbval.sbvalue.GetType()
                is_float = self._lldb_tp_isfp(tp)
                if is_float:
                    return lldbval.sbvalue.GetValue()
                else:
                    return str(int(lldbval))

            s = lldbval.sbvalue.GetValue()
            if s[:2] == '0x':
                # Strip useless leading zeros.
                res = s[2:].lstrip('0')
                return '0x' + (res if res else '0')
            return s

        def lldb__sub__(lldbval, other):
            if type(other) is not lldb.value or \
               type(other) is lldb.value and \
               not other.sbvalue.TypeIsPointerType():
                other = int(other)
            if type(other) is int:
                return lldb__add__(lldbval, -other)
            elif lldbval.sbvalue.TypeIsPointerType():
                sbval = lldbval.sbvalue
                osbval = other.sbvalue
                lldbval_tp = sbval.GetType()
                other_tp = osbval.GetType()
                # Subtract pointers of the same size only.
                elsz = lldbval_tp.GetDereferencedType().size
                if other_tp.GetDereferencedType().size != elsz:
                    raise Exception(
                        'Attempt to substruct {otp} from {stp}'.format(
                            stp=lldbval_tp.name,
                            otp=other_tp.name
                        )
                    )
                diff = sbval.GetValueAsUnsigned() - osbval.GetValueAsUnsigned()
                return int(diff / elsz)
            else:
                return int(lldbval) - int(other)

        super(_LLDBDebugger, self).__init__()
        self.target = lldb.debugger.GetSelectedTarget()
        # Monkey-patch the lldb.value class.
        lldb.value.__add__ = lldb__add__
        lldb.value.__bool__ = lldb__bool__
        lldb.value.__ge__ = lldb__ge__
        lldb.value.__getitem__ = lldb__getitem__
        lldb.value.__gt__ = lldb__gt__
        lldb.value.__le__ = lldb__le__
        lldb.value.__lt__ = lldb__lt__
        lldb.value.__str__ = lldb__str__
        lldb.value.__sub__ = lldb__sub__

        def lldb_major_version():
            version_string = lldb.SBDebugger.GetVersionString()
            match = re.search(r'(\d+)', version_string)
            if match:
                return int(match.group(1))
            return None

        # Needed for features detection.
        self.version = lldb_major_version()

    def _dbgtype(self, typestr):
        if typestr in self.dbgtype_cache:
            return self.dbgtype_cache[typestr]

        m = re.match(r'((?:(?:struct|union) )?\S*)\s*[*]', typestr)

        dbgtype = self.target.FindFirstType(typestr) if m is None \
            else self.target.FindFirstType(m.group(1)).GetPointerType()

        self.dbgtype_cache[typestr] = dbgtype
        return dbgtype

    def cast(self, typestr, val):
        if isinstance(val, lldb.value):
            val = val.sbvalue
        elif type(val) is int:
            tp = self._dbgtype(typestr)
            return self._lldb_value_from_raw(val, tp.GetByteSize(), tp)
        elif not isinstance(val, lldb.SBValue):
            raise Exception(
                'Unexpected cast from type: {t}.'.format(t=type(val))
            )

        # XXX: Simply SBValue.Cast() works incorrectly since it
        # may take the 8 bytes of memory instead of 4, before the
        # cast. Construct the value on the fly.
        tp = self._dbgtype(typestr)
        if self._lldb_tp_isfp(tp):
            rawval = float(val.GetValue())
        elif self._lldb_tp_issigned(tp):
            rawval = val.GetValueAsSigned()
        else:
            rawval = val.GetValueAsUnsigned()
        return self._lldb_value_from_raw(rawval, val.GetByteSize(), tp)

    def sizeof(self, typestr):
        return self._dbgtype(typestr).GetByteSize()

    def offsetof(self, typestr, fieldstr):
        def _type_member(type_obj, name):
            return next((x for x in type_obj.members if x.name == name), None)

        type_obj = self._dbgtype(typestr)
        member = _type_member(type_obj, fieldstr)
        assert member is not None, 'There is no field {f} in {t}'.format(
            f=fieldstr,
            t=typestr,
        )
        return member.GetOffsetInBytes()

    def cstr(self, strptr):
        return strptr.sbvalue.summary

    def lookup_global(self, symbol):
        return self.target.FindFirstGlobalVariable(symbol)

    def eval(self, command):
        if not command:
            return None

        process = self.target.GetProcess()
        thread = process.GetSelectedThread()
        frame = thread.GetSelectedFrame()
        ret = frame.EvaluateExpression(command)
        return ret

    def write(self, msg):
        sys.stdout.write(msg)

    def check_libluajit(self):
        # TODO: Implement postpone loading for LLDB too.
        return True

    def init_luajit_arch(self):
        global LJ_64, LJ_DUALNUM, LJ_FR2, LJ_GC64
        IRT_P64 = 9
        module = self.target.modules[0]
        dualnum_sym = module.FindSymbol('lj_lib_checknumber')
        LJ_DUALNUM = dualnum_sym is not None and dualnum_sym.IsValid()
        irtype_enum = self.target.FindFirstType('IRType').enum_members
        for member in irtype_enum:
            if member.name == 'IRT_PTR':
                LJ_64 = member.unsigned & 0x1f == IRT_P64
            if member.name == 'IRT_PGC':
                LJ_FR2 = LJ_GC64 = member.unsigned & 0x1f == IRT_P64

    def register_command(self, command, name):
        command.name = name
        lldb.debugger.HandleCommand(
            'command script add {o} --class luajit_dbg.{cls} {cmd}'.format(
                o='--overwrite' if self.version >= 14 else '',
                cls=command.__name__,
                cmd=name,
            )
        )

    class LJBase(object):
        # Ignore given parameters by LLDB.
        def __init__(ljbase, debugger, unused):
            pass

        def get_short_help(ljbase):
            return ljbase.__doc__.splitlines()[1]

        def get_long_help(ljbase):
            return ljbase.__doc__

        def __call__(ljbase, debugger, args, exe_ctx, result):
            try:
                ljbase.execute(args)
            except Exception as e:
                msg = 'Failed to execute command `{}`: {}'.format(
                    ljbase.name,
                    e
                )
                result.SetError(msg)

        @abc.abstractmethod
        def execute(ljbase, args):
            '''Implementation of the command.
            Subclasses override this method to implement the logic of a given
            command, e.g. printing a stack. Any unhandled exception will be
            automatically transformed into proper errors.
            '''

    LJBase = LJBase


dbg = Debugger()


# LuaJIT. ########################################################


# Constants.


LJ_64 = None
LJ_DUALNUM = None
LJ_FR2 = None
LJ_GC64 = None

LJ_GCVMASK = ((1 << 47) - 1)
LJ_TISNUM = None
PADDING = None

# These constants are meaningful only for 'LJ_64' mode.
LJ_LIGHTUD_BITS_SEG = 8
LJ_LIGHTUD_BITS_LO = 47 - LJ_LIGHTUD_BITS_SEG
LIGHTUD_SEG_MASK = (1 << LJ_LIGHTUD_BITS_SEG) - 1
LIGHTUD_LO_MASK = (1 << LJ_LIGHTUD_BITS_LO) - 1


# Simple converters.


def tou64(val):
    return dbg.cast('uint64_t', val) & 0xFFFFFFFFFFFFFFFF


def tou32(val):
    return int(val) & 0xFFFFFFFF


def i2notu32(val):
    return ~int(val) & 0xFFFFFFFF


def strx64(val):
    return re.sub('L?$', '', hex(int(tou64(val))))


# Types and TValues.


LJ_T = {
    'NIL':     i2notu32(0),
    'FALSE':   i2notu32(1),
    'TRUE':    i2notu32(2),
    'LIGHTUD': i2notu32(3),
    'STR':     i2notu32(4),
    'UPVAL':   i2notu32(5),
    'THREAD':  i2notu32(6),
    'PROTO':   i2notu32(7),
    'FUNC':    i2notu32(8),
    'TRACE':   i2notu32(9),
    'CDATA':   i2notu32(10),
    'TAB':     i2notu32(11),
    'UDATA':   i2notu32(12),
    'NUMX':    i2notu32(13),
}


def typenames(value):
    return {
        LJ_T[k]: 'LJ_T' + k for k in LJ_T.keys()
    }.get(int(value), 'LJ_TINVALID')


def itype(o):
    return tou32(o['it64'] >> 47) if LJ_GC64 else o['it']


def tvisint(o):
    return LJ_DUALNUM and itype(o) == LJ_TISNUM


def tvisnumber(o):
    return itype(o) <= LJ_TISNUM


def tvislightud(o):
    if LJ_64 and not LJ_GC64:
        return (dbg.cast('int32_t', itype(o)) >> 15) == -2
    else:
        return itype(o) == LJ_T['LIGHTUD']


def itypemap(o):
    if LJ_64 and not LJ_GC64:
        return LJ_T['NUMX'] if tvisnumber(o)       \
            else LJ_T['LIGHTUD'] if tvislightud(o) \
            else itype(o)
    else:
        return LJ_T['NUMX'] if tvisnumber(o) else itype(o)


# Frames.


FRAME_TYPE = 0x3
FRAME_P = 0x4
FRAME_TYPEP = FRAME_TYPE | FRAME_P

FRAME = {
    'LUA':    0x0,
    'C':      0x1,
    'CONT':   0x2,
    'VARG':   0x3,
    'LUAP':   0x4,
    'CP':     0x5,
    'PCALL':  0x6,
    'PCALLH': 0x7,
}


def frametypes(ft):
    return {
        FRAME['LUA']:  'L',
        FRAME['C']:    'C',
        FRAME['CONT']: 'M',
        FRAME['VARG']: 'V',
    }.get(ft, '?')


def bc_a(ins):
    return (ins >> 8) & 0xff


def frame_ftsz(framelink):
    return dbg.cast('ptrdiff_t', framelink['ftsz'] if LJ_FR2
                    else framelink['fr']['tp']['ftsz'])


def frame_pc(framelink):
    return dbg.cast('BCIns *', frame_ftsz(framelink)) if LJ_FR2 \
        else mref('BCIns *', framelink['fr']['tp']['pcr'])


def frame_prevl(framelink):
    return framelink - (1 + LJ_FR2 + bc_a(frame_pc(framelink)[-1]))


def frame_ispcall(framelink):
    return (frame_ftsz(framelink) & FRAME['PCALL']) == FRAME['PCALL']


def frame_sized(framelink):
    return (frame_ftsz(framelink) & ~FRAME_TYPEP)


def frame_prevd(framelink):
    return dbg.cast('TValue *',
                    dbg.cast('char *', framelink) - frame_sized(framelink))


def frame_type(framelink):
    return frame_ftsz(framelink) & FRAME_TYPE


def frame_typep(framelink):
    return frame_ftsz(framelink) & FRAME_TYPEP


def frame_islua(framelink):
    return frametypes(int(frame_type(framelink))) == 'L' \
        and int(frame_ftsz(framelink)) > 0


def frame_prev(framelink):
    return frame_prevl(framelink) if frame_islua(framelink) \
        else frame_prevd(framelink)


def frame_sentinel(L):
    return mref('TValue *', L['stack']) + LJ_FR2


# The generator that implements frame iterator.
# Every frame is represented as a tuple of framelink and frametop.
def frames(L):
    frametop = L['top']
    framelink = L['base'] - 1
    framelink_sentinel = frame_sentinel(L)
    while True:
        yield framelink, frametop
        frametop = framelink - (1 + LJ_FR2)
        if framelink <= framelink_sentinel:
            break
        framelink = frame_prev(framelink)


# LuaJIT macro implementations and structure access.


def mref(typename, obj):
    return dbg.cast(typename, obj['ptr64'] if LJ_GC64 else obj['ptr32'])


def gcref(obj):
    return dbg.cast('GCobj *', obj['gcptr64'] if LJ_GC64
                    else dbg.cast('uintptr_t', obj['gcptr32']))


def gcval(obj):
    return dbg.cast('GCobj *', obj['gcptr64'] & LJ_GCVMASK if LJ_GC64
                    else dbg.cast('uintptr_t', obj['gcptr32']))


def gcnext(obj):
    return gcref(obj)['gch']['nextgc']


def L(L=None):
    # Look up a symbol for the main coroutine considering the host
    # application.
    # XXX Fragile: Though the loop initialization looks bad, it
    # respects both Python 2 and Python 3.
    for lstate in [L] + list(map(lambda main: dbg.lookup_global(main), (
        # LuaJIT main coro (see luajit/src/luajit.c).
        'globalL',
        # Tarantool main coro (see tarantool/src/lua/init.h).
        'tarantool_L',
        # TODO: Add more.
    ))):
        if lstate:
            return dbg.cast('lua_State *', lstate)


def G(L):
    return mref('global_State *', L['glref'])


def J(g):
    g_offset = dbg.offsetof('GG_State', 'g')
    J_offset = dbg.offsetof('GG_State', 'J')
    return dbg.cast('jit_State *', dbg.cast('char *', g) - g_offset + J_offset)


def vm_state(g):
    return {
        i2notu32(0): 'INTERP',
        i2notu32(1): 'LFUNC',
        i2notu32(2): 'FFUNC',
        i2notu32(3): 'CFUNC',
        i2notu32(4): 'GC',
        i2notu32(5): 'EXIT',
        i2notu32(6): 'RECORD',
        i2notu32(7): 'OPT',
        i2notu32(8): 'ASM',
    }.get(int(tou32(g['vmstate'])), 'TRACE')


def gc_state(g):
    return {
        0: 'PAUSE',
        1: 'PROPAGATE',
        2: 'ATOMIC',
        3: 'SWEEPSTRING',
        4: 'SWEEP',
        5: 'FINALIZE',
        6: 'LAST',
    }.get(int(g['gc']['state']), 'INVALID')


def jit_state(g):
    return {
        0:    'IDLE',
        0x10: 'ACTIVE',
        0x11: 'RECORD',
        0x12: 'START',
        0x13: 'END',
        0x14: 'ASM',
        0x15: 'ERR',
    }.get(int(J(g)['state']), 'INVALID')


def strdata(obj):
    try:
        return dbg.cstr(dbg.cast('char *', dbg.cast('GCstr *', obj) + 1))
    except UnicodeEncodeError:
        return "<luajit_dbg: error occurred while rendering non-ascii slot>"


def funcproto(func):
    assert func['ffid'] == 0, 'Attempt to take a prototype of non-Lua function'
    return dbg.cast('GCproto *',
                    mref('char *', func['pc']) - dbg.sizeof('GCproto'))


def gclistlen(root, end=0x0):
    count = 0
    while (gcref(root) != end):
        count += 1
        root = gcnext(root)
    return count


def gcringlen(root):
    if not gcref(root):
        return 0
    elif gcref(root) == gcref(gcnext(root)):
        return 1
    else:
        return 1 + gclistlen(gcnext(root), gcref(root))


gclen = {
    'root':      gclistlen,
    'gray':      gclistlen,
    'grayagain': gclistlen,
    'weak':      gclistlen,
    # XXX: gc.mmudata is a ring-list.
    'mmudata':   gcringlen,
}


def lightudV(tv):
    if LJ_64:
        u = int(tv['u64'])
        # `lightudseg()' macro expanded.
        seg = (u >> LJ_LIGHTUD_BITS_LO) & LIGHTUD_SEG_MASK
        segmap = mref('uint32_t *', G(L(None))['gc']['lightudseg'])
        # `lightudlo()' macro expanded.
        return (int(segmap[seg]) << 32) | (u & LIGHTUD_LO_MASK)
    else:
        return gcval(tv['gcr'])


# Dumpers.


def dump_lj_tnil(tv):
    return 'nil'


def dump_lj_tfalse(tv):
    return 'false'


def dump_lj_ttrue(tv):
    return 'true'


def dump_lj_tlightud(tv):
    return 'light userdata @ {}'.format(strx64(lightudV(tv)))


def dump_lj_tstr(tv):
    return 'string {body} @ {address}'.format(
        body=strdata(gcval(tv['gcr'])),
        address=strx64(gcval(tv['gcr']))
    )


def dump_lj_tupval(tv):
    return 'upvalue @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tthread(tv):
    return 'thread @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tproto(tv):
    return 'proto @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tfunc(tv):
    func = dbg.cast('struct GCfuncC *', gcval(tv['gcr']))
    ffid = func['ffid']

    if ffid == 0:
        pt = funcproto(func)
        return 'Lua function @ {addr}, {nups} upvalues, {chunk}:{line}'.format(
            addr=strx64(func),
            nups=int(func['nupvalues']),
            chunk=strdata(dbg.cast('GCstr *', gcval(pt['chunkname']))),
            line=pt['firstline']
        )
    elif ffid == 1:
        return 'C function @ {}'.format(strx64(func['f']))
    else:
        return 'fast function #{}'.format(int(ffid))


def dump_lj_ttrace(tv):
    trace = dbg.cast('struct GCtrace *', gcval(tv['gcr']))
    return 'trace {traceno} @ {addr}'.format(
        traceno=strx64(trace['traceno']),
        addr=strx64(trace)
    )


def dump_lj_tcdata(tv):
    return 'cdata @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_ttab(tv):
    table = dbg.cast('GCtab *', gcval(tv['gcr']))
    return 'table @ {gcr} (asize: {asize}, hmask: {hmask})'.format(
        gcr=strx64(table),
        asize=table['asize'],
        hmask=strx64(table['hmask']),
    )


def dump_lj_tudata(tv):
    return 'userdata @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tnumx(tv):
    if tvisint(tv):
        return 'integer {}'.format(dbg.cast('int32_t', tv['i']))
    else:
        return 'number {}'.format(dbg.cast('double', tv['n']))


def dump_lj_invalid(tv):
    return 'not valid type @ {}'.format(strx64(gcval(tv['gcr'])))


dumpers = {
    'LJ_TNIL':     dump_lj_tnil,
    'LJ_TFALSE':   dump_lj_tfalse,
    'LJ_TTRUE':    dump_lj_ttrue,
    'LJ_TLIGHTUD': dump_lj_tlightud,
    'LJ_TSTR':     dump_lj_tstr,
    'LJ_TUPVAL':   dump_lj_tupval,
    'LJ_TTHREAD':  dump_lj_tthread,
    'LJ_TPROTO':   dump_lj_tproto,
    'LJ_TFUNC':    dump_lj_tfunc,
    'LJ_TTRACE':   dump_lj_ttrace,
    'LJ_TCDATA':   dump_lj_tcdata,
    'LJ_TTAB':     dump_lj_ttab,
    'LJ_TUDATA':   dump_lj_tudata,
    'LJ_TNUMX':    dump_lj_tnumx,
}


def dump_tvalue(tvalue):
    return dumpers.get(typenames(itypemap(tvalue)), dump_lj_invalid)(tvalue)


def dump_framelink_slot_address(fr):
    return '{}:{}'.format(fr - 1, fr) if LJ_FR2 \
        else '{}'.format(fr) + PADDING


def dump_framelink(L, fr):
    if fr == frame_sentinel(L):
        return '{addr} [S   ] FRAME: dummy L'.format(
            addr=dump_framelink_slot_address(fr),
        )
    return '{addr} [    ] FRAME: [{pp}] delta={d}, {f}'.format(
        addr=dump_framelink_slot_address(fr),
        pp='PP' if frame_ispcall(fr) else '{frname}{p}'.format(
            frname=frametypes(int(frame_type(fr))),
            p='P' if frame_typep(fr) & FRAME_P else ''
        ),
        d=dbg.cast('TValue *', fr) - dbg.cast('TValue *', frame_prev(fr)),
        f=dump_lj_tfunc(fr - LJ_FR2),
    )


def dump_stack_slot(L, slot, base=None, top=None):
    base = base or L['base']
    top = top or L['top']

    return '{addr}{padding} [ {B}{T}{M}] VALUE: {value}'.format(
        addr=strx64(slot),
        padding=PADDING,
        B='B' if slot == base else ' ',
        T='T' if slot == top else ' ',
        M='M' if slot == mref('TValue *', L['maxstack']) else ' ',
        value=dump_tvalue(slot),
    )


def dump_stack(L, base=None, top=None):
    base = base or L['base']
    top = top or L['top']
    stack = mref('TValue *', L['stack'])
    maxstack = mref('TValue *', L['maxstack'])
    red = 5 + 3 * LJ_FR2

    dump = [
        '{padding} Red zone: {nredslots: >2} slots {padding}'.format(
            padding='-' * len(PADDING),
            nredslots=red,
        ),
    ]
    dump.extend([
        dump_stack_slot(L, maxstack + offset, base, top)
            for offset in range(red, 0, -1)  # noqa: E131
    ])
    dump.extend([
        '{padding} Stack: {nstackslots: >5} slots {padding}'.format(
            padding='-' * len(PADDING),
            nstackslots=int((tou64(maxstack) - tou64(stack)) >> 3),
        ),
        dump_stack_slot(L, maxstack, base, top),
        '{start}:{end} [    ] {nfreeslots} slots: Free stack slots'.format(
            start=strx64(top + 1),
            end=strx64(maxstack - 1),
            nfreeslots=int((tou64(maxstack) - tou64(top) - 8) >> 3),
        ),
    ])

    for framelink, frametop in frames(L):
        # Dump all data slots in the (framelink, top) interval.
        dump.extend([
            dump_stack_slot(L, framelink + offset, base, top)
                for offset in range(frametop - framelink, 0, -1)  # noqa: E131
        ])
        # Dump frame slot (2 slots in case of GC64).
        dump.append(dump_framelink(L, framelink))

    return '\n'.join(dump)


def dump_gc(g):
    gc = g['gc']
    stats = ['{key}: {value}'.format(key=f, value=gc[f]) for f in (
        'total', 'threshold', 'debt', 'estimate', 'stepmul', 'pause'
    )]

    stats += ['sweepstr: {sweepstr}/{strmask}'.format(
        sweepstr=gc['sweepstr'],
        # String hash mask (size of hash table - 1).
        strmask=g['strmask'] + 1,
    )]

    stats += ['{key}: {number} objects'.format(
        key=stat,
        number=handler(gc[stat])
    ) for stat, handler in gclen.items()]

    return '\n'.join(map(lambda s: '\t' + s, stats))


# Extension commands. ############################################


class LJDumpArch(dbg.LJBase):
    '''
lj-arch

The command requires no args and dumps values of LJ_64 and LJ_GC64
compile-time flags. These values define the sizes of host and GC
pointers, respectively.
    '''

    def execute(self, arg):
        dbg.write(
            'LJ_64: {LJ_64}, LJ_GC64: {LJ_GC64}, LJ_DUALNUM: {LJ_DUALNUM}\n'
            .format(
                LJ_64=LJ_64,
                LJ_GC64=LJ_GC64,
                LJ_DUALNUM=LJ_DUALNUM
            )
        )


class LJGC(dbg.LJBase):
    '''
lj-gc

The command requires no args and dumps current GC stats:
* total: <total number of allocated bytes in GC area>
* threshold: <limit when gc step is triggered>
* debt: <how much GC is behind schedule>
* estimate: <estimate of memory actually in use>
* stepmul: <incremental GC step granularity>
* pause: <pause between successive GC cycles>
* sweepstr: <sweep position in string table>
* root: <number of all collectable objects>
* gray: <number of gray objects>
* grayagain: <number of objects for atomic traversal>
* weak: <number of weak tables (to be cleared)>
* mmudata: <number of udata|cdata to be finalized>
    '''

    def execute(self, arg):
        g = G(L(None))
        dbg.write('GC stats: {state}\n{stats}\n'.format(
            state=gc_state(g),
            stats=dump_gc(g)
        ))


class LJDumpStack(dbg.LJBase):
    '''
lj-stack [<lua_State *>]

The command receives a lua_State address and dumps the given Lua
coroutine guest stack:

<slot ptr> [<slot attributes>] <VALUE|FRAME>

* <slot ptr>: guest stack slot address
* <slot attributes>:
  - S: Bottom of the stack (the slot L->stack points to)
  - B: Base of the current guest frame (the slot L->base points to)
  - T: Top of the current guest frame (the slot L->top points to)
  - M: Last slot of the stack (the slot L->maxstack points to)
* <VALUE>: See help lj-tv for more info
* <FRAME>: Framelink slot differs from the value slot: it contains info
  related to the function being executed within this guest frame, its
  type, and a link to the parent guest frame
  [<frame type>] delta=<slots in frame>, <lj-tv for LJ_TFUNC slot>
  - <frame type>:
    + L:  VM performs a call as a result of bytecode execution
    + C:  VM performs a call as a result of lj_vm_call
    + M:  VM performs a call to a metamethod as a result of bytecode
          execution
    + V:  Variable-length frame for storing arguments of a variadic
          function
    + CP: Protected C frame
    + PP: VM performs a call as a result of executing pcall or xpcall

If L is omitted, the main coroutine is used.
    '''

    def execute(self, arg):
        dbg.write('{}\n'.format(dump_stack(L(dbg.eval(arg)))))


class LJState(dbg.LJBase):
    '''
lj-state
The command requires no args and dumps current VM and GC states:
* VM state: <INTERP|C|GC|EXIT|RECORD|OPT|ASM|TRACE>
* GC state: <PAUSE|PROPAGATE|ATOMIC|SWEEPSTRING|SWEEP|FINALIZE|LAST>
* JIT state: <IDLE|ACTIVE|RECORD|START|END|ASM|ERR>
    '''

    def execute(self, arg):
        g = G(L(None))
        dbg.write('{}\n'.format('\n'.join(
            map(lambda t: '{} state: {}'.format(*t), {
                'VM':  vm_state(g),
                'GC':  gc_state(g),
                'JIT': jit_state(g),
            }.items())
        )))


class LJDumpString(dbg.LJBase):
    '''
lj-str <GCstr *>

The command receives a <gcr> of the corresponding GCstr object and dumps
the payload, size in bytes and hash.

*Caveat*: Since Python 2 provides no native Unicode support, the payload
is replaced with the corresponding error when decoding fails.
    '''

    def execute(self, arg):
        string = dbg.cast('GCstr *', dbg.eval(arg))
        dbg.write("String: {body} [{len} bytes] with hash {hash}\n".format(
            body=strdata(string),
            hash=strx64(string['hash']),
            len=string['len'],
        ))


class LJDumpTable(dbg.LJBase):
    '''
lj-tab <GCtab *>

The command receives a GCtab address and dumps the table contents:
* Metatable address whether the one is set
* Array part <asize> slots:
  <aslot ptr>: [<index>]: <tv>
* Hash part <hsize> nodes:
  <hnode ptr>: { <tv> } => { <tv> }; next = <next hnode ptr>
    '''

    def execute(self, arg):
        t = dbg.cast('GCtab *', dbg.eval(arg))
        array = mref('TValue *', t['array'])
        nodes = mref('struct Node *', t['node'])
        mt = gcval(t['metatable'])
        capacity = {
            'apart': int(t['asize']),
            'hpart': int(t['hmask'] + 1) if t['hmask'] > 0 else 0
        }

        if mt != 0:
            dbg.write('Metatable detected: {}\n'.format(strx64(mt)))

        dbg.write('Array part: {} slots\n'.format(capacity['apart']))
        for i in range(capacity['apart']):
            slot = array + i
            dbg.write('{ptr}: [{index}]: {value}\n'.format(
                ptr=slot,
                index=i,
                value=dump_tvalue(slot)
            ))

        dbg.write('Hash part: {} nodes\n'.format(capacity['hpart']))
        # See hmask comment in lj_obj.h
        for i in range(capacity['hpart']):
            node = nodes + i
            dbg.write('{ptr}: {{ {key} }} => {{ {val} }}; next = {n}\n'.format(
                ptr=node,
                key=dump_tvalue(node['key']),
                val=dump_tvalue(node['val']),
                n=mref('struct Node *', node['next'])
            ))


class LJDumpTValue(dbg.LJBase):
    '''
lj-tv <TValue *>

The command receives a pointer to <tv> (TValue address) and dumps
the type and some info related to it.

* LJ_TNIL: nil
* LJ_TFALSE: false
* LJ_TTRUE: true
* LJ_TLIGHTUD: light userdata @ <gcr>
* LJ_TSTR: string <string payload> @ <gcr>
* LJ_TUPVAL: upvalue @ <gcr>
* LJ_TTHREAD: thread @ <gcr>
* LJ_TPROTO: proto @ <gcr>
* LJ_TFUNC: <LFUNC|CFUNC|FFUNC>
  <LFUNC>: Lua function @ <gcr>, <nupvals> upvalues, <chunk:line>
  <CFUNC>: C function <mcode address>
  <FFUNC>: fast function #<ffid>
* LJ_TTRACE: trace <traceno> @ <gcr>
* LJ_TCDATA: cdata @ <gcr>
* LJ_TTAB: table @ <gcr> (asize: <asize>, hmask: <hmask>)
* LJ_TUDATA: userdata @ <gcr>
* LJ_TNUMX: <number|integer> <numeric payload>

Whether the type of the given address differs from the listed above, then
error message occurs.
    '''

    def execute(self, arg):
        tv = dbg.cast('TValue *', dbg.eval(arg))
        dbg.write('{}\n'.format(dump_tvalue(tv)))


def load(event=None):
    dbg.initialize_extension({
        'lj-arch':  LJDumpArch,
        'lj-gc':    LJGC,
        'lj-stack': LJDumpStack,
        'lj-state': LJState,
        'lj-str':   LJDumpString,
        'lj-tab':   LJDumpTable,
        'lj-tv':    LJDumpTValue,
    })


if gdb:
    load()
elif lldb:
    def __lldb_init_module(debugger, internal_dictionary):
        load()
