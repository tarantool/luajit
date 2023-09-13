# Debug extension for LuaJIT post-mortem analysis.
# To use in LLDB: 'command script import <path-to-repo>/src/luajit_dbg.py'
# To use in GDB: 'source <path-to-repo>/src/luajit_dbg.py'

import abc
import re
import sys
import types

from importlib import import_module

# Make the script compatible with the ancient Python {{{


LEGACY = re.match(r'^2\.', sys.version)

if LEGACY:
    CONNECTED = False
    int = long
    range = xrange


def is_integer_type(val):
    return isinstance(val, int) or (LEGACY and isinstance(val, types.IntType))


# }}}


class Debugger(object):
    def __init__(self):
        self.GDB = False
        self.LLDB = False
        self.type_cache = {}

        # XXX: While the `gdb` library is only available inside
        # a debug session, the `lldb` library can be loaded in
        # any Python script. To address that, we need to perform
        # an additional check to ensure a debug session is
        # actually running.
        debuggers = {
            'gdb': lambda lib: True,
            'lldb': lambda lib: lib.debugger is not None,
        }
        for name, healthcheck in debuggers.items():
            lib = None
            try:
                lib = import_module(name)
                if healthcheck(lib):
                    setattr(self, name.upper(), True)
                    globals()[name] = lib
                    self.name = name
            except Exception:
                continue

        assert self.LLDB != self.GDB

    def setup_target(self, debugger):
        global target
        if self.LLDB:
            target = debugger.GetSelectedTarget()

    def write(self, msg):
        if self.LLDB:
            print(msg)
        else:
            gdb.write(msg + '\n')

    def cmd_init(self, cmd_cls, debugger=None):
        if self.LLDB:
            debugger.HandleCommand(
                'command script add --overwrite --class '
                'luajit_dbg.{cls} {cmd}'
                .format(
                    cls=cmd_cls.__name__,
                    cmd=cmd_cls.command,
                )
            )
        else:
            cmd_cls()

    def event_connect(self, callback):
        if not self.LLDB:
            # XXX Fragile: though connecting the callback looks like a crap but
            # it respects both Python 2 and Python 3 (see #4828).
            if LEGACY:
                global CONNECTED
                CONNECTED = True
            gdb.events.new_objfile.connect(callback)

    def event_disconnect(self, callback):
        if not self.LLDB:
            # XXX Fragile: though disconnecting the callback looks like a crap
            # but it respects both Python 2 and Python 3 (see #4828).
            if LEGACY:
                global CONNECTED
                if not CONNECTED:
                    return
                CONNECTED = False
            gdb.events.new_objfile.disconnect(callback)

    def lookup_variable(self, name):
        if self.LLDB:
            return target.FindFirstGlobalVariable(name)
        else:
            variable, _ = gdb.lookup_symbol(name)
            return variable.value() if variable else None

    def lookup_symbol(self, sym):
        if self.LLDB:
            return target.modules[0].FindSymbol(sym)
        else:
            return gdb.lookup_global_symbol(sym)

    def to_unsigned(self, val):
        return val.unsigned if self.LLDB else int(val)

    def to_signed(self, val):
        return val.signed if self.LLDB else int(val)

    def to_str(self, val):
        return val.value if self.LLDB else str(val)

    def find_type(self, typename):
        if typename not in self.type_cache:
            if self.LLDB:
                self.type_cache[typename] = target.FindFirstType(typename)
            else:
                self.type_cache[typename] = gdb.lookup_type(typename)
        return self.type_cache[typename]

    def type_to_pointer_type(self, tp):
        if self.LLDB:
            return tp.GetPointerType()
        else:
            return tp.pointer()

    def cast_impl(self, value, t, pointer_type):
        if self.LLDB:
            if is_integer_type(value):
                # Integer casts require some black magic
                # for lldb to behave properly.
                if pointer_type:
                    return target.CreateValueFromAddress(
                        'value',
                        lldb.SBAddress(value, target),
                        t.GetPointeeType(),
                    ).address_of
                else:
                    return target.CreateValueFromData(
                        name='value',
                        data=lldb.SBData.CreateDataFromInt(value, size=8),
                        type=t,
                    )
            else:
                return value.Cast(t)
        else:
            return gdb.Value(value).cast(t)

    def dereference(self, val):
        if self.LLDB:
            return val.Dereference()
        else:
            return val.dereference()

    def eval(self, expression):
        if self.LLDB:
            process = target.GetProcess()
            thread = process.GetSelectedThread()
            frame = thread.GetSelectedFrame()

            if not expression:
                return None

            return frame.EvaluateExpression(expression)
        else:
            return gdb.parse_and_eval(expression)

    def type_sizeof_impl(self, tp):
        if self.LLDB:
            return tp.GetByteSize()
        else:
            return tp.sizeof

    def summary(self, val):
        if self.LLDB:
            return val.summary
        else:
            return str(val)[len(PADDING):].strip()

    def type_member(self, type_obj, name):
        if self.LLDB:
            return next((x for x in type_obj.members if x.name == name), None)
        else:
            return type_obj[name]

    def type_member_offset(self, member):
        if self.LLDB:
            return member.GetOffsetInBytes()
        else:
            return member.bitpos // 8

    def get_member(self, value, member_name):
        if self.LLDB:
            return value.GetChildMemberWithName(member_name)
        else:
            return value[member_name]

    def address_of(self, value):
        if self.LLDB:
            return value.address_of
        else:
            return value.address

    def arch_init(self):
        global LJ_64, LJ_GC64, LJ_FR2, LJ_DUALNUM, PADDING, LJ_TISNUM, target
        if self.LLDB:
            irtype_enum = dbg.find_type('IRType').enum_members
            for member in irtype_enum:
                if member.name == 'IRT_PTR':
                    LJ_64 = dbg.to_unsigned(member) & 0x1f == IRT_P64
                if member.name == 'IRT_PGC':
                    LJ_GC64 = dbg.to_unsigned(member) & 0x1f == IRT_P64
        else:
            LJ_64 = str(dbg.eval('IRT_PTR')) == 'IRT_P64'
            LJ_GC64 = str(dbg.eval('IRT_PGC')) == 'IRT_P64'

        LJ_FR2 = LJ_GC64
        LJ_DUALNUM = dbg.lookup_symbol('lj_lib_checknumber') is not None
        # Two extra characters are required to fit in the `0x` part.
        PADDING = ' ' * len(strx64(L()))
        LJ_TISNUM = 0xfffeffff if LJ_64 and not LJ_GC64 else LJ_T['NUMX']


dbg = Debugger()

LJ_64 = None
LJ_GC64 = None
LJ_FR2 = None
LJ_DUALNUM = None
PADDING = None

# Constants
IRT_P64 = 9
LJ_GCVMASK = ((1 << 47) - 1)
LJ_TISNUM = None

# Global
target = None


class Ptr(object):
    def __init__(self, value, normal_type):
        self.value = value
        self.normal_type = normal_type

    @property
    def __deref(self):
        return self.normal_type(dbg.dereference(self.value))

    def __add__(self, other):
        assert is_integer_type(other)
        return self.__class__(
            cast(
                self.normal_type.__name__ + ' *',
                cast(
                    'uintptr_t',
                    dbg.to_unsigned(self.value) + other * sizeof(
                        self.normal_type.__name__
                    ),
                ),
            ),
        )

    def __sub__(self, other):
        assert is_integer_type(other) or isinstance(other, Ptr)
        if is_integer_type(other):
            return self.__add__(-other)
        else:
            return int(
                (
                    dbg.to_unsigned(self.value) - dbg.to_unsigned(other.value)
                ) / sizeof(self.normal_type.__name__)
            )

    def __eq__(self, other):
        assert isinstance(other, Ptr) or is_integer_type(other)
        if isinstance(other, Ptr):
            return dbg.to_unsigned(self.value) == dbg.to_unsigned(other.value)
        else:
            return dbg.to_unsigned(self.value) == other

    def __ne__(self, other):
        return not self == other

    def __gt__(self, other):
        assert isinstance(other, Ptr)
        return dbg.to_unsigned(self.value) > dbg.to_unsigned(other.value)

    def __ge__(self, other):
        assert isinstance(other, Ptr)
        return dbg.to_unsigned(self.value) >= dbg.to_unsigned(other.value)

    def __bool__(self):
        return dbg.to_unsigned(self.value) != 0

    def __int__(self):
        return dbg.to_unsigned(self.value)

    def __long__(self):
        return dbg.to_unsigned(self.value)

    def __str__(self):
        return dbg.to_str(self.value)

    def __getattr__(self, name):
        if name != '__deref':
            return getattr(self.__deref, name)
        return self.__deref


class Struct(object):
    def __init__(self, value):
        self.value = value

    def __getitem__(self, name):
        return dbg.get_member(self.value, name)

    @property
    def addr(self):
        return dbg.address_of(self.value)


c_structs = {
    'MRef': [
        (property(lambda self: dbg.to_unsigned(self['ptr64']) if LJ_GC64
                  else dbg.to_unsigned(self['ptr32'])), 'ptr')
    ],
    'GCRef': [
        (property(lambda self: dbg.to_unsigned(self['gcptr64']) if LJ_GC64
                  else dbg.to_unsigned(self['gcptr32'])), 'gcptr')
    ],
    'TValue': [
        ('GCRef', 'gcr'),
        ('uint', 'it'),
        ('uint', 'i'),
        ('int', 'it64'),
        ('string', 'n'),
        (property(lambda self: FR(self['fr']) if not LJ_GC64 else None), 'fr'),
        (
            property(
                lambda self: dbg.to_signed(self['ftsz']) if LJ_GC64 else None
            ),
            'ftsz'
        )
    ],
    'GCState': [
        ('GCRef', 'root'),
        ('GCRef', 'gray'),
        ('GCRef', 'grayagain'),
        ('GCRef', 'weak'),
        ('GCRef', 'mmudata'),
        ('uint', 'state'),
        ('uint', 'total'),
        ('uint', 'threshold'),
        ('uint', 'debt'),
        ('uint', 'estimate'),
        ('uint', 'stepmul'),
        ('uint', 'pause'),
        ('uint', 'sweepstr')
    ],
    'lua_State': [
        ('MRef', 'glref'),
        ('MRef', 'stack'),
        ('MRef', 'maxstack'),
        ('TValuePtr', 'top'),
        ('TValuePtr', 'base')
    ],
    'global_State': [
        ('GCState', 'gc'),
        ('uint', 'vmstate'),
        ('uint', 'strmask')
    ],
    'jit_State': [
        ('uint', 'state')
    ],
    'GChead': [
        ('GCRef', 'nextgc')
    ],
    'GCobj': [
        ('GChead', 'gch')
    ],
    'GCstr': [
        ('uint', 'hash'),
        ('uint', 'len')
    ],
    'FrameLink': [
        ('MRef', 'pcr'),
        ('int', 'ftsz')
    ],
    'FR': [
        ('FrameLink', 'tp')
    ],
    'GCfuncC': [
        ('MRef', 'pc'),
        ('uint', 'ffid'),
        ('uint', 'nupvalues'),
        ('uint', 'f')
    ],
    'GCtab': [
        ('MRef', 'array'),
        ('MRef', 'node'),
        ('GCRef', 'metatable'),
        ('uint', 'asize'),
        ('uint', 'hmask')
    ],
    'GCproto': [
        ('GCRef', 'chunkname'),
        ('int', 'firstline')
    ],
    'GCtrace': [
        ('uint', 'traceno')
    ],
    'Node': [
        ('TValue', 'key'),
        ('TValue', 'val'),
        ('MRef', 'next')
    ],
    'BCIns': [],
}


def make_property_from_metadata(field, tp):
    builtin = {
        'uint':   dbg.to_unsigned,
        'int':    dbg.to_signed,
        'string': dbg.to_str,
    }
    if tp in builtin.keys():
        return lambda self: builtin[tp](self[field])
    else:
        return lambda self: globals()[tp](self[field])


for cls, metainfo in c_structs.items():
    cls_dict = {}
    for field in metainfo:
        prop_constructor = field[0]
        prop_name = field[1]
        if not isinstance(prop_constructor, str):
            cls_dict[prop_name] = prop_constructor
        else:
            cls_dict[prop_name] = property(
                make_property_from_metadata(prop_name, prop_constructor)
            )
    globals()[cls] = type(cls, (Struct, ), cls_dict)


for cls in Struct.__subclasses__():
    ptr_name = cls.__name__ + 'Ptr'

    def make_init(cls):
        return lambda self, value: super(type(self), self).__init__(value, cls)

    globals()[ptr_name] = type(ptr_name, (Ptr,), {
        '__init__': make_init(cls)
    })


class Command(object if dbg.LLDB else gdb.Command):
    def __init__(self, debugger=None, unused=None):
        if dbg.GDB:
            # XXX Fragile: though initialization looks like a crap but it
            # respects both Python 2 and Python 3 (see #4828).
            gdb.Command.__init__(self, self.command, gdb.COMMAND_DATA)

    def get_short_help(self):
        return self.__doc__.splitlines()[0]

    def get_long_help(self):
        return self.__doc__

    def __call__(self, debugger, command, exe_ctx, result):
        try:
            self.execute(command)
        except Exception as e:
            msg = 'Failed to execute command `{}`: {}'.format(self.command, e)
            result.SetError(msg)

    def parse(self, command):
        if not command:
            return None
        return dbg.to_unsigned(dbg.eval(command))

    @abc.abstractproperty
    def command(self):
        """Command name.
        This name will be used by LLDB in order to unique/ly identify an
        implementation that should be executed when a command is run
        in the REPL.
        """

    @abc.abstractmethod
    def execute(self, args):
        """Implementation of the command.
        Subclasses override this method to implement the logic of a given
        command, e.g. printing a stacktrace. The command output should be
        communicated back via the provided result object, so that it's
        properly routed to LLDB frontend. Any unhandled exception will be
        automatically transformed into proper errors.
        """
    def invoke(self, arg, from_tty):
        try:
            self.execute(arg)
        except Exception as e:
            dbg.write(e)


def cast(typename, value):
    pointer_type = False
    name = None
    if isinstance(value, Struct) or isinstance(value, Ptr):
        # Get underlying value, if passed object is a wrapper.
        value = value.value

    # Obtain base type name, decide whether it's a pointer.
    if isinstance(typename, type):
        name = typename.__name__
        if name.endswith('Ptr'):
            pointer_type = True
            name = name[:-3]
    else:
        name = typename
        if name[-1] == '*':
            name = name[:-1].strip()
            pointer_type = True

    # Get the inferior type representation.
    t = dbg.find_type(name)
    if pointer_type:
        t = dbg.type_to_pointer_type(t)

    casted = dbg.cast_impl(value, t, pointer_type)

    if isinstance(typename, type):
        # Wrap inferior object, if possible
        return typename(casted)
    else:
        return casted


def offsetof(typename, membername):
    type_obj = dbg.find_type(typename)
    member = dbg.type_member(type_obj, membername)
    assert member is not None
    return dbg.type_member_offset(member)


def sizeof(typename):
    type_obj = dbg.find_type(typename)
    return dbg.type_sizeof_impl(type_obj)


def vtou64(value):
    return dbg.to_unsigned(value) & 0xFFFFFFFFFFFFFFFF


def vtoi(value):
    return dbg.to_signed(value)


def gcval(obj):
    return cast(GCobjPtr, cast('uintptr_t', obj.gcptr & LJ_GCVMASK) if LJ_GC64
                else cast('uintptr_t', obj.gcptr))


def gcref(obj):
    return cast(GCobjPtr, obj.gcptr if LJ_GC64
                else cast('uintptr_t', obj.gcptr))


def gcnext(obj):
    return gcref(obj).gch.nextgc


def gclistlen(root, end=0x0):
    count = 0
    while (gcref(root) != end):
        count += 1
        root = gcnext(root)
    return count


def gcringlen(root):
    if gcref(root) == 0:
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


def dump_gc(g):
    gc = g.gc
    stats = ['{key}: {value}'.format(key=f, value=getattr(gc, f)) for f in (
        'total', 'threshold', 'debt', 'estimate', 'stepmul', 'pause'
    )]

    stats += ['sweepstr: {sweepstr}/{strmask}'.format(
        sweepstr=gc.sweepstr,
        # String hash mask (size of hash table - 1).
        strmask=g.strmask + 1,
    )]

    stats += ['{key}: {number} objects'.format(
        key=stat,
        number=handler(getattr(gc, stat))
    ) for stat, handler in gclen.items()]
    return '\n'.join(map(lambda s: '\t' + s, stats))


def mref(typename, obj):
    return cast(typename, obj.ptr)


def J(g):
    g_offset = offsetof('GG_State', 'g')
    J_offset = offsetof('GG_State', 'J')
    return cast(
        jit_StatePtr,
        int(vtou64(cast('char *', g)) - g_offset + J_offset),
    )


def G(L):
    return mref(global_StatePtr, L.glref)


def L(L=None):
    # lookup a symbol for the main coroutine considering the host app
    # XXX Fragile: though the loop initialization looks like a crap but it
    # respects both Python 2 and Python 3.
    for lstate in [L] + list(map(lambda main: dbg.lookup_variable(main), (
        # LuaJIT main coro (see luajit/src/luajit.c)
        'globalL',
        # Tarantool main coro (see tarantool/src/lua/init.h)
        'tarantool_L',
        # TODO: Add more
    ))):
        if lstate:
            return lua_StatePtr(lstate)


def tou32(val):
    return val & 0xFFFFFFFF


def i2notu32(val):
    return ~int(val) & 0xFFFFFFFF


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
    }.get(int(tou32(g.vmstate)), 'TRACE')


def gc_state(g):
    return {
        0: 'PAUSE',
        1: 'PROPAGATE',
        2: 'ATOMIC',
        3: 'SWEEPSTRING',
        4: 'SWEEP',
        5: 'FINALIZE',
        6: 'LAST',
    }.get(g.gc.state, 'INVALID')


def jit_state(g):
    return {
        0:    'IDLE',
        0x10: 'ACTIVE',
        0x11: 'RECORD',
        0x12: 'START',
        0x13: 'END',
        0x14: 'ASM',
        0x15: 'ERR',
    }.get(J(g).state, 'INVALID')


def strx64(val):
    return re.sub('L?$', '',
                  hex(int(val) & 0xFFFFFFFFFFFFFFFF))


def funcproto(func):
    assert func.ffid == 0
    proto_size = sizeof('GCproto')
    value = cast('uintptr_t', vtou64(mref('char *', func.pc)) - proto_size)
    return cast(GCprotoPtr, value)


def strdata(obj):
    try:
        ptr = cast('char *', obj + 1)
        return dbg.summary(ptr)
    except UnicodeEncodeError:
        return "<luajit_dbg: error occured while rendering non-ascii slot>"


def itype(o):
    return tou32(o.it64 >> 47) if LJ_GC64 else o.it


def tvisint(o):
    return LJ_DUALNUM and itype(o) == LJ_TISNUM


def tvislightud(o):
    if LJ_64 and not LJ_GC64:
        return (vtoi(cast('int32_t', itype(o))) >> 15) == -2
    else:
        return itype(o) == LJ_T['LIGHTUD']


def tvisnumber(o):
    return itype(o) <= LJ_TISNUM


def dump_lj_tnil(tv):
    return 'nil'


def dump_lj_tfalse(tv):
    return 'false'


def dump_lj_ttrue(tv):
    return 'true'


def dump_lj_tlightud(tv):
    return 'light userdata @ {}'.format(strx64(gcval(tv.gcr)))


def dump_lj_tstr(tv):
    return 'string {body} @ {address}'.format(
        body=strdata(cast(GCstrPtr, gcval(tv.gcr))),
        address=strx64(gcval(tv.gcr))
    )


def dump_lj_tupval(tv):
    return 'upvalue @ {}'.format(strx64(gcval(tv.gcr)))


def dump_lj_tthread(tv):
    return 'thread @ {}'.format(strx64(gcval(tv.gcr)))


def dump_lj_tproto(tv):
    return 'proto @ {}'.format(strx64(gcval(tv.gcr)))


def dump_lj_tfunc(tv):
    func = cast(GCfuncCPtr, gcval(tv.gcr))
    ffid = func.ffid

    if ffid == 0:
        pt = funcproto(func)
        return 'Lua function @ {addr}, {nups} upvalues, {chunk}:{line}'.format(
            addr=strx64(func),
            nups=func.nupvalues,
            chunk=strdata(cast(GCstrPtr, gcval(pt.chunkname))),
            line=pt.firstline
        )
    elif ffid == 1:
        return 'C function @ {}'.format(strx64(func.f))
    else:
        return 'fast function #{}'.format(ffid)


def dump_lj_ttrace(tv):
    trace = cast(GCtracePtr, gcval(tv.gcr))
    return 'trace {traceno} @ {addr}'.format(
        traceno=strx64(trace.traceno),
        addr=strx64(trace)
    )


def dump_lj_tcdata(tv):
    return 'cdata @ {}'.format(strx64(gcval(tv.gcr)))


def dump_lj_ttab(tv):
    table = cast(GCtabPtr, gcval(tv.gcr))
    return 'table @ {gcr} (asize: {asize}, hmask: {hmask})'.format(
        gcr=strx64(table),
        asize=table.asize,
        hmask=strx64(table.hmask),
    )


def dump_lj_tudata(tv):
    return 'userdata @ {}'.format(strx64(gcval(tv.gcr)))


def dump_lj_tnumx(tv):
    if tvisint(tv):
        return 'integer {}'.format(cast('int32_t', tv.i))
    else:
        return 'number {}'.format(tv.n)


def dump_lj_invalid(tv):
    return 'not valid type @ {}'.format(strx64(gcval(tv.gcr)))


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


def itypemap(o):
    if LJ_64 and not LJ_GC64:
        return LJ_T['NUMX'] if tvisnumber(o) \
            else LJ_T['LIGHTUD'] if tvislightud(o) else itype(o)
    else:
        return LJ_T['NUMX'] if tvisnumber(o) else itype(o)


def typenames(value):
    return {
        LJ_T[k]: 'LJ_T' + k for k in LJ_T.keys()
    }.get(int(value), 'LJ_TINVALID')


def dump_tvalue(tvptr):
    return dumpers.get(typenames(itypemap(tvptr)), dump_lj_invalid)(tvptr)


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
    return vtou64(cast('ptrdiff_t', framelink.ftsz if LJ_FR2
                       else framelink.fr.tp.ftsz))


def frame_pc(framelink):
    return cast(BCInsPtr, frame_ftsz(framelink)) if LJ_FR2 \
        else mref(BCInsPtr, framelink.fr.tp.pcr)


def frame_prevl(framelink):
    # We are evaluating the `frame_pc(framelink)[-1])` with
    # REPL, because the lldb API is faulty and it's not possible to cast
    # a struct member of 32-bit type to 64-bit type without getting onto
    # the next property bits, despite the fact that it's an actual value, not
    # a pointer to it.
    bcins = vtou64(dbg.eval('((BCIns *)' + str(frame_pc(framelink)) + ')[-1]'))
    return framelink - (1 + LJ_FR2 + bc_a(bcins))


def frame_ispcall(framelink):
    return (frame_ftsz(framelink) & FRAME['PCALL']) == FRAME['PCALL']


def frame_sized(framelink):
    return (frame_ftsz(framelink) & ~FRAME_TYPEP)


def frame_prevd(framelink):
    return framelink - int(frame_sized(framelink) / sizeof('TValue'))


def frame_type(framelink):
    return frame_ftsz(framelink) & FRAME_TYPE


def frame_typep(framelink):
    return frame_ftsz(framelink) & FRAME_TYPEP


def frame_islua(framelink):
    return frametypes(frame_type(framelink)) == 'L' \
        and frame_ftsz(framelink) > 0


def frame_prev(framelink):
    return frame_prevl(framelink) if frame_islua(framelink) \
        else frame_prevd(framelink)


def frame_sentinel(L):
    return mref(TValuePtr, L.stack) + LJ_FR2


# The generator that implements frame iterator.
# Every frame is represented as a tuple of framelink and frametop.
def frames(L):
    frametop = L.top
    framelink = L.base - 1
    framelink_sentinel = frame_sentinel(L)
    while True:
        yield framelink, frametop
        frametop = framelink - (1 + LJ_FR2)
        if framelink <= framelink_sentinel:
            break
        framelink = frame_prev(framelink)


def dump_framelink_slot_address(fr):
    return '{start:{padding}}:{end:{padding}}'.format(
        start=strx64(fr - 1),
        end=strx64(fr),
        padding=len(PADDING),
    ) if LJ_FR2 else '{addr:{padding}}'.format(
        addr=strx64(fr),
        padding=2 * len(PADDING) + 1,
    )


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
        d=fr - frame_prev(fr),
        f=dump_lj_tfunc(fr - LJ_FR2),
    )


def dump_stack_slot(L, slot, base=None, top=None):
    base = base or L.base
    top = top or L.top

    return '{addr:{padding}} [ {B}{T}{M}] VALUE: {value}'.format(
        addr=strx64(slot),
        padding=2 * len(PADDING) + 1,
        B='B' if slot == base else ' ',
        T='T' if slot == top else ' ',
        M='M' if slot == mref(TValuePtr, L.maxstack) else ' ',
        value=dump_tvalue(slot),
    )


def dump_stack(L, base=None, top=None):
    base = base or L.base
    top = top or L.top
    stack = mref(TValuePtr, L.stack)
    maxstack = mref(TValuePtr, L.maxstack)
    red = 5 + 2 * LJ_FR2

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
            nstackslots=int((maxstack - stack) >> 3),
        ),
        dump_stack_slot(L, maxstack, base, top),
        '{start}:{end} [    ] {nfreeslots} slots: Free stack slots'.format(
            start='{address:{padding}}'.format(
                address=strx64(top + 1),
                padding=len(PADDING),
            ),
            end='{address:{padding}}'.format(
                address=strx64(maxstack - 1),
                padding=len(PADDING),
            ),
            nfreeslots=int((maxstack - top - 8) >> 3),
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


class LJDumpTValue(Command):
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
* LJ_TNUMX: number <numeric payload>

Whether the type of the given address differs from the listed above, then
error message occurs.
    '''
    command = 'lj-tv'

    def execute(self, args):
        tvptr = TValuePtr(cast('TValue *', self.parse(args)))
        dbg.write('{}'.format(dump_tvalue(tvptr)))


class LJState(Command):
    '''
lj-state
The command requires no args and dumps current VM and GC states
* VM state: <INTERP|C|GC|EXIT|RECORD|OPT|ASM|TRACE>
* GC state: <PAUSE|PROPAGATE|ATOMIC|SWEEPSTRING|SWEEP|FINALIZE|LAST>
* JIT state: <IDLE|ACTIVE|RECORD|START|END|ASM|ERR>
    '''
    command = 'lj-state'

    def execute(self, args):
        g = G(L(None))
        dbg.write('{}'.format('\n'.join(
            map(lambda t: '{} state: {}'.format(*t), {
                'VM':  vm_state(g),
                'GC':  gc_state(g),
                'JIT': jit_state(g),
            }.items())
        )))


class LJDumpArch(Command):
    '''
lj-arch

The command requires no args and dumps values of LJ_64 and LJ_GC64
compile-time flags. These values define the sizes of host and GC
pointers respectively.
    '''
    command = 'lj-arch'

    def execute(self, args):
        dbg.write(
            'LJ_64: {LJ_64}, LJ_GC64: {LJ_GC64}, LJ_DUALNUM: {LJ_DUALNUM}'
            .format(
                LJ_64=LJ_64,
                LJ_GC64=LJ_GC64,
                LJ_DUALNUM=LJ_DUALNUM
            )
        )


class LJGC(Command):
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
    command = 'lj-gc'

    def execute(self, args):
        g = G(L(None))
        dbg.write('GC stats: {state}\n{stats}'.format(
            state=gc_state(g),
            stats=dump_gc(g)
        ))


class LJDumpString(Command):
    '''
lj-str <GCstr *>

The command receives a <gcr> of the corresponding GCstr object and dumps
the payload, size in bytes and hash.

*Caveat*: Since Python 2 provides no native Unicode support, the payload
is replaced with the corresponding error when decoding fails.
    '''
    command = 'lj-str'

    def execute(self, args):
        string_ptr = GCstrPtr(cast('GCstr *', self.parse(args)))
        dbg.write("String: {body} [{len} bytes] with hash {hash}".format(
            body=strdata(string_ptr),
            hash=strx64(string_ptr.hash),
            len=string_ptr.len,
        ))


class LJDumpTable(Command):
    '''
lj-tab <GCtab *>

The command receives a GCtab address and dumps the table contents:
* Metatable address whether the one is set
* Array part <asize> slots:
  <aslot ptr>: [<index>]: <tv>
* Hash part <hsize> nodes:
  <hnode ptr>: { <tv> } => { <tv> }; next = <next hnode ptr>
    '''
    command = 'lj-tab'

    def execute(self, args):
        t = GCtabPtr(cast('GCtab *', self.parse(args)))
        array = mref(TValuePtr, t.array)
        nodes = mref(NodePtr, t.node)
        mt = gcval(t.metatable)
        capacity = {
            'apart': int(t.asize),
            'hpart': int(t.hmask + 1) if t.hmask > 0 else 0
        }

        if mt:
            dbg.write('Metatable detected: {}'.format(strx64(mt)))

        dbg.write('Array part: {} slots'.format(capacity['apart']))
        for i in range(capacity['apart']):
            slot = array + i
            dbg.write('{ptr}: [{index}]: {value}'.format(
                ptr=strx64(slot),
                index=i,
                value=dump_tvalue(slot)
            ))

        dbg.write('Hash part: {} nodes'.format(capacity['hpart']))
        # See hmask comment in lj_obj.h
        for i in range(capacity['hpart']):
            node = nodes + i
            dbg.write('{ptr}: {{ {key} }} => {{ {val} }}; next = {n}'.format(
                ptr=strx64(node),
                key=dump_tvalue(TValuePtr(node.key.addr)),
                val=dump_tvalue(TValuePtr(node.val.addr)),
                n=strx64(mref(NodePtr, node.next))
            ))


class LJDumpStack(Command):
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
* <VALUE>: see help lj-tv for more info
* <FRAME>: framelink slot differs from the value slot: it contains info
  related to the function being executed within this guest frame, its
  type and link to the parent guest frame
  [<frame type>] delta=<slots in frame>, <lj-tv for LJ_TFUNC slot>
  - <frame type>:
    + L:  VM performs a call as a result of bytecode execution
    + C:  VM performs a call as a result of lj_vm_call
    + M:  VM performs a call to a metamethod as a result of bytecode
          execution
    + V:  Variable-length frame for storing arguments of a variadic
          function
    + CP: Protected C frame
    + PP: VM performs a call as a result of executinig pcall or xpcall

If L is omitted the main coroutine is used.
    '''
    command = 'lj-stack'

    def execute(self, args):
        lstate = self.parse(args)
        lstate_ptr = cast('lua_State *', lstate) if lstate else None
        dbg.write('{}'.format(dump_stack(L(lstate_ptr))))


LJ_COMMANDS = [
    LJDumpTValue,
    LJState,
    LJDumpArch,
    LJGC,
    LJDumpString,
    LJDumpTable,
    LJDumpStack,
]


def register_commands(commands, debugger=None):
    for cls in commands:
        dbg.cmd_init(cls, debugger)
        dbg.write('{cmd} command intialized'.format(cmd=cls.command))


def configure(debugger=None):
    global PADDING, LJ_TISNUM, LJ_DUALNUM
    dbg.setup_target(debugger)
    try:
        # Try to remove the callback at first to not append duplicates to
        # gdb.events.new_objfile internal list.
        dbg.event_disconnect(load)
    except Exception:
        # Callback is not connected.
        pass

    try:
        # Detect whether libluajit objfile is loaded.
        dbg.eval('luaJIT_setmode')
    except Exception:
        dbg.write('luajit_dbg.py initialization is postponed '
                  'until libluajit objfile is loaded\n')
        # Add a callback to be executed when the next objfile is loaded.
        dbg.event_connect(load)
        return False

    try:
        dbg.arch_init()
    except Exception:
        dbg.write('LuaJIT debug extension failed to load: '
                  'no debugging symbols found for libluajit')
        return False
    return True


# XXX: The dummy parameter is needed for this function to
# work as a gdb callback.
def load(_=None, debugger=None):
    if configure(debugger):
        register_commands(LJ_COMMANDS, debugger)
        dbg.write('LuaJIT debug extension is successfully loaded')


def __lldb_init_module(debugger, _=None):
    load(None, debugger)


if dbg.GDB:
    load()
