# LLDB extension for LuaJIT post-mortem analysis.
# To use, just put 'command script import <path-to-repo>/src/luajit_lldb.py'
# in lldb.

import abc
import re
import lldb

LJ_64 = None
LJ_GC64 = None
LJ_FR2 = None
LJ_DUALNUM = None
LJ_TISNUM = None

# Constants
IRT_P64 = 9
LJ_GCVMASK = (1 << 47) - 1
NO_BCPOS = ~0
PROTO_VARARG = 0x02
FF_LUA = 0
FF_C = 1
VARNAMES = [
    '(for index)',
    '(for limit)',
    '(for step)',
    '(for generator)',
    '(for state)',
    '(for control)',
]
VARNAME_END = 0
VARNAME__MAX = len(VARNAMES) + 1

# Debugger specific {{{

# Global
target = None
luajit_module = None
PADDING = None


class Ptr:
    def __init__(self, value, normal_type):
        self.value = value
        self.normal_type = normal_type

    @property
    def __deref(self):
        return self.normal_type(self.value.Dereference())

    def __add__(self, other):
        assert isinstance(other, int)
        return self.__class__(
            cast(
                self.normal_type.__name__ + ' *',
                cast(
                    'uintptr_t',
                    self.value.unsigned + other * self.value.deref.size,
                ),
            ),
        )  # pyright: ignore[reportCallIssue]

    def __sub__(self, other):
        assert isinstance(other, int) or isinstance(other, Ptr)
        if isinstance(other, int):
            return self.__add__(-other)
        else:
            return int(
                (self.value.unsigned - other.value.unsigned)
                / sizeof(self.normal_type.__name__)
            )

    def __eq__(self, other):
        assert isinstance(other, Ptr) or isinstance(other, int) and other >= 0
        if isinstance(other, Ptr):
            return self.value.unsigned == other.value.unsigned
        else:
            return self.value.unsigned == other

    def __ne__(self, other):
        return not self == other

    def __gt__(self, other):
        assert isinstance(other, Ptr)
        return self.value.unsigned > other.value.unsigned

    def __ge__(self, other):
        assert isinstance(other, Ptr)
        return self.value.unsigned >= other.value.unsigned

    def __bool__(self):
        return self.value.unsigned != 0

    def __int__(self):
        return self.value.unsigned

    def __str__(self):
        if not self.value:
            return 'NULL'

        return self.value.value

    def __getattr__(self, name):
        if name != '__deref':
            return getattr(self.__deref, name)
        return self.__deref


class MetaStruct(type):
    def __init__(cls, name, bases, nmspc):
        super(MetaStruct, cls).__init__(name, bases, nmspc)

        def make_general(field, tp):
            builtin = {
                'uint': 'unsigned',
                'int': 'signed',
                'string': 'value',
            }
            if tp in builtin.keys():
                return lambda self: getattr(self[field], builtin[tp])
            else:
                return lambda self: globals()[tp](self[field])

        if hasattr(cls, 'metainfo'):
            for field in cls.metainfo:  # pyright: ignore[reportAttributeAccessIssue]
                if not isinstance(field[0], str):
                    setattr(cls, field[1], field[0])
                else:
                    setattr(
                        cls,
                        field[1],
                        property(make_general(field[1], field[0])),
                    )


class Struct(metaclass=MetaStruct):
    def __init__(self, value):
        self.value = value

    def __getitem__(self, name):
        return self.value.GetChildMemberWithName(name)

    @property
    def addr(self):
        return self.value.address_of


c_structs = {
    'MRef': [
        (
            property(lambda self: self['ptr64' if LJ_GC64 else 'ptr32'].unsigned),
            'ptr',
        )
    ],
    'GCRef': [
        (
            property(lambda self: self['gcptr64' if LJ_GC64 else 'gcptr32'].unsigned),
            'gcptr',
        )
    ],
    'TValue': [
        ('GCRef', 'gcr'),
        ('uint', 'it'),
        ('uint', 'i'),
        ('int', 'it64'),
        ('string', 'n'),
        (property(lambda self: FR(self['fr']) if not LJ_GC64 else None), 'fr'),
        (property(lambda self: self['ftsz'].signed if LJ_GC64 else None), 'ftsz'),
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
        ('uint', 'sweepstr'),
    ],
    'lua_State': [
        ('uint', 'status'),
        ('MRef', 'glref'),
        ('TValuePtr', 'base'),
        ('TValuePtr', 'top'),
        ('MRef', 'maxstack'),
        ('MRef', 'stack'),
    ],
    'global_State': [
        ('GCState', 'gc'),
        ('uint', 'vmstate'),
        ('uint', 'strmask'),
        ('GCRef', 'mainthref'),
        ('GCRef', 'cur_L'),
    ],
    'jit_State': [('uint', 'state')],
    'GChead': [('GCRef', 'nextgc'), ('uint', 'gct')],
    'GCobj': [('GChead', 'gch')],
    'GCstr': [('uint', 'hash'), ('uint', 'len')],
    'FrameLink': [('MRef', 'pcr'), ('int', 'ftsz')],
    'FR': [('FrameLink', 'tp')],
    'GCfuncC': [('MRef', 'pc'), ('uint', 'ffid'), ('uint', 'nupvalues'), ('uint', 'f')],
    'GCtab': [
        ('MRef', 'array'),
        ('MRef', 'node'),
        ('GCRef', 'metatable'),
        ('uint', 'asize'),
        ('uint', 'hmask'),
    ],
    'GCproto': [
        ('GCRef', 'chunkname'),
        ('int', 'firstline'),
        ('int', 'numline'),
        ('int', 'numparams'),
        ('int', 'flags'),
        ('MRef', 'varinfo'),
    ],
    'GCtrace': [('uint', 'traceno')],
    'Node': [('TValue', 'key'), ('TValue', 'val'), ('MRef', 'next')],
    'BCIns': [],
}

for cls in c_structs.keys():
    globals()[cls] = type(cls, (Struct,), {'metainfo': c_structs[cls]})

for cls in Struct.__subclasses__():
    ptr_name = cls.__name__ + 'Ptr'

    globals()[ptr_name] = type(
        ptr_name,
        (Ptr,),
        {
            '__init__': lambda self, value, cls=cls: super(type(self), self).__init__(
                value, cls
            )
        },
    )


class Command(object):
    def __init__(self, debugger, unused):
        pass

    def get_short_help(self):
        return self.__doc__.splitlines()[0]

    def get_long_help(self):
        return self.__doc__

    def __call__(self, debugger, command, exe_ctx, result):
        try:
            self.execute(debugger, command, result)
        except Exception as e:
            msg = 'Failed to execute command `{}`: {}'.format(self.command, e)
            result.SetError(msg)

    def parse(self, command):
        process = target.GetProcess()
        thread = process.GetSelectedThread()
        frame = thread.GetSelectedFrame()

        if not command:
            return None

        ret = frame.EvaluateExpression(command)
        return ret

    @property
    @abc.abstractmethod
    def command(self):
        """Command name.
        This name will be used by LLDB in order to unique/ly identify an
        implementation that should be executed when a command is run
        in the REPL.
        """

    @abc.abstractmethod
    def execute(self, debugger, args, result):
        """Implementation of the command.
        Subclasses override this method to implement the logic of a given
        command, e.g. printing a stacktrace. The command output should be
        communicated back via the provided result object, so that it's
        properly routed to LLDB frontend. Any unhandled exception will be
        automatically transformed into proper errors.
        """


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

    # Get the lldb type representation.
    t = find_type(name)
    if pointer_type:
        t = t.GetPointerType()

    if isinstance(value, int):
        # Integer casts require some black magic for lldb to behave properly.
        if pointer_type:
            casted = target.CreateValueFromAddress(
                'value',
                lldb.SBAddress(value, target),
                t.GetPointeeType(),
            ).address_of
        else:
            casted = target.CreateValueFromData(
                name='value',
                data=lldb.SBData.CreateDataFromInt(value, size=8),
                type=t,
            )
    else:
        casted = value.Cast(t)

    if isinstance(typename, type):
        # Wrap lldb object, if possible
        return typename(casted)
    else:
        return casted


def lookup_global(name):
    return target.FindFirstGlobalVariable(name)


def type_member(type_obj, name):
    return next((x for x in type_obj.members if x.name == name), None)


def find_type(typename):
    return luajit_module.FindFirstType(typename)


def offsetof(typename, membername):
    type_obj = find_type(typename)
    member = type_member(type_obj, membername)
    assert member is not None
    return member.GetOffsetInBytes()


def sizeof(typename):
    type_obj = find_type(typename)
    return type_obj.GetByteSize()


def vtou64(value):
    return value.unsigned & 0xFFFFFFFFFFFFFFFF


def vtoi(value):
    return value.signed


def dbg_eval(expr):
    process = target.GetProcess()
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()
    return frame.EvaluateExpression(expr)


# }}} Debugger specific


def gcval(obj):
    return cast(
        GCobjPtr,
        cast('uintptr_t', obj.gcr.gcptr & LJ_GCVMASK if LJ_GC64 else obj.gcr.gcptr),
    )


def gcref(obj):
    return cast(GCobjPtr, obj.gcptr if LJ_GC64 else cast('uintptr_t', obj.gcptr))


def gcnext(obj):
    return gcref(obj).gch.nextgc


def gclistlen(root, end=0x0):
    count = 0
    while gcref(root) != end:
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
    'root': gclistlen,
    'gray': gclistlen,
    'grayagain': gclistlen,
    'weak': gclistlen,
    # XXX: gc.mmudata is a ring-list.
    'mmudata': gcringlen,
}


def dump_gc(g):
    gc = g.gc
    stats = [
        '{key}: {value}'.format(key=f, value=getattr(gc, f))
        for f in ('total', 'threshold', 'debt', 'estimate', 'stepmul', 'pause')
    ]

    stats += [
        'sweepstr: {sweepstr}/{strmask}'.format(
            sweepstr=gc.sweepstr,
            # String hash mask (size of hash table - 1).
            strmask=g.strmask + 1,
        )
    ]

    stats += [
        '{key}: {number} objects'.format(key=stat, number=handler(getattr(gc, stat)))
        for stat, handler in gclen.items()
    ]
    return '\n'.join(map(lambda s: '\t' + s, stats))


def mref(typename, obj):
    return cast(typename, obj.ptr)


def J(g):
    g_offset = offsetof('GG_State', 'g')
    J_offset = offsetof('GG_State', 'J')
    return cast(
        jit_StatePtr,
        vtou64(cast('char *', g)) - (g_offset + J_offset),
    )


def G(L):
    return mref(global_StatePtr, L.glref)


def L(L=None):
    # lookup a symbol for the main coroutine considering the host app
    # XXX Fragile: though the loop initialization looks like a crap but it
    # respects both Python 2 and Python 3.
    for lstate in [L] + list(
        map(
            lambda main: lookup_global(main),
            (
                # LuaJIT main coro (see luajit/src/luajit.c)
                'globalL',
                # Tarantool main coro (see tarantool/src/lua/init.h)
                'tarantool_L',
                # TODO: Add more
            ),
        )
    ):
        if lstate:
            return lua_State(lstate)


def mainthread(g):
    return gcref(g.mainthref)


def cur_L(g):
    return gcref(g.cur_L)


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
        0: 'IDLE',
        0x10: 'ACTIVE',
        0x11: 'RECORD',
        0x12: 'START',
        0x13: 'END',
        0x14: 'ASM',
        0x15: 'ERR',
    }.get(J(g).state, 'INVALID')


def strx64(val):
    return re.sub('L?$', '', hex(int(val) & 0xFFFFFFFFFFFFFFFF))


def isluafunc(func):
    return func.ffid == FF_LUA


def iscfunc(func):
    return func.ffid == FF_C


def isffunc(func):
    return func.ffid > FF_C


def funcproto(func):
    assert isluafunc(func)
    proto_size = sizeof('GCproto')
    value = cast('uintptr_t', vtou64(mref('char *', func.pc)) - proto_size)
    return cast(GCprotoPtr, value)


def strdata(obj):
    try:
        ptr = cast('char *', obj + 1)

        return ptr.summary
    except UnicodeEncodeError:
        return "<luajit-lldb: error occurred while rendering non-ascii slot>"


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
    return 'light userdata @ {}'.format(strx64(gcval(tv)))


def dump_lj_tstr(o):
    return 'string {body} @ {address}'.format(
        body=strdata(cast(GCstrPtr, o)), address=strx64(o)
    )


def dump_lj_tupval(o):
    return 'upvalue @ {}'.format(strx64(o))


def thread_state(t):
    return {
        0: 'OK',
        1: 'YIELD',
        2: 'ERRRUN',
        3: 'ERRSYNTAX',
        4: 'ERRMEM',
        5: 'ERRERR',
        5
        + 1: 'ERRERR+1',  # Appeared in error handlers as 'Don't touch the stack during ...'
    }.get(t.status, 'INVALID')


def dump_lj_tthread(o):
    thread = cast(lua_StatePtr, o)

    info = [
        'main' if thread == mainthread(G(thread)) else None,
        'curL' if thread == cur_L(G(thread)) else None,
        thread_state(thread),
    ]

    info = ' '.join(item for item in info if item)

    if info:
        info += ' '

    return '{info}thread @ {addr}'.format(info=info, addr=thread)


def dump_lj_tproto(gcobj):
    proto = cast(GCprotoPtr, gcobj)

    return 'proto {chunkname}:{firstline}-{lastline} @ {addr}'.format(
        chunkname=proto_chunkname(proto),
        firstline=proto.firstline,
        lastline=proto.firstline + proto.numline,
        addr=strx64(proto),
    )


def proto_chunkname(pt):
    if not pt.chunkname:
        return None

    return strdata(cast(GCstrPtr, gcref(pt.chunkname)))


def dump_lj_tfunc(o):
    func = cast(GCfuncCPtr, o)

    if isluafunc(func):
        pt = funcproto(func)
        return 'Lua function @ {addr}, {nparams} params, {vararg}{nups} upvalues, {chunk}:{line}'.format(
            addr=strx64(func),
            nparams=pt.numparams,
            vararg='vararg, ' if pt.flags & PROTO_VARARG else '',
            nups=func.nupvalues,
            chunk=proto_chunkname(pt),
            line=pt.firstline,
        )
    elif iscfunc(func):
        return 'C function @ {} ({})'.format(
            strx64(func.f), target.ResolveLoadAddress(func.f)
        )
    else:
        return 'fast function #{} ({})'.format(
            func.ffid, target.ResolveLoadAddress(func.f).function.name
        )


def debug_framepc(L, func, nextframe):
    return dbg_eval(
        f'(BCPos)debug_framepc((lua_State*){L.value.value}, (GCfunc*){func}, (cTValue*){nextframe})'
    ).signed


def debug_frameline(L, func, nextframe):
    pc = debug_framepc(L, func, nextframe)

    if pc != NO_BCPOS:
        pt = funcproto(func)

        return dbg_eval(f'(BCLine)lj_debug_line((GCproto *){pt}, (BCPos){pc})').signed

    return -1


def lj_debug_funcname(L, frame):
    FUNCNAME_VARIABLE_NAME = '$lj_debug_funcname_name'

    name = dbg_eval(f'{FUNCNAME_VARIABLE_NAME} = NULL; &{FUNCNAME_VARIABLE_NAME}')

    if not name.value:
        name = dbg_eval(
            f'const char* {FUNCNAME_VARIABLE_NAME} = NULL; &{FUNCNAME_VARIABLE_NAME}'
        )

    try:
        namewhat = dbg_eval(
            f'(const char *)lj_debug_funcname((lua_State *){L.value.value}, (cTValue *){frame}, &{FUNCNAME_VARIABLE_NAME})'
        )

        if namewhat.unsigned == 0:
            return '', None

        return namewhat.summary, name.Dereference().summary
    except UnicodeEncodeError:
        error = '<luajit-lldb: error occurred while rendering non-ascii slot>'
        return error, error
    except:
        return '', None


def lj_debug_getinfo(L, tv, frame, nextframe):
    func = cast(GCfuncCPtr, gcval(tv))

    if isluafunc(func):
        pt = funcproto(func)

        source = proto_chunkname(pt)
        if not source:
            return None

        what = 'Lua' if (pt.firstline or not pt.numline) else 'm'
    else:
        source = '[C]'
        what = 'C'

    currentline = debug_frameline(L, func, nextframe)
    namewhat, name = lj_debug_funcname(L, frame)

    result = ''

    if isffunc(func) and not namewhat:
        result += f'[builtin#{func.ffid}]:'
    else:
        result += f'{source}:'

    if currentline > 0:
        result += f'{currentline}:'

    if namewhat:
        result += f' in function {name}'
    else:
        if what == 'm':
            result += ' in main chunk'
        elif what == 'C':
            result += f' at {strx64(func.f)}'
        else:
            result += f' in function <{source}:{0}>'

    return result


def dump_lj_ttrace(tv):
    trace = cast(GCtracePtr, gcval(tv))
    return 'trace {traceno} @ {addr}'.format(
        traceno=strx64(trace.traceno), addr=strx64(trace)
    )


def dump_lj_tcdata(o):
    return 'cdata @ {}'.format(strx64(o))


def dump_lj_ttab(o):
    table = cast(GCtabPtr, o)
    return 'table @ {gcr} (asize: {asize}, hmask: {hmask})'.format(
        gcr=strx64(table),
        asize=table.asize,
        hmask=strx64(table.hmask),
    )


def dump_lj_tudata(o):
    return 'userdata @ {}'.format(strx64(o))


def dump_lj_tnumx(tv):
    if tvisint(tv):
        return 'integer {}'.format(cast('int32_t', tv.i))
    else:
        return 'number {}'.format(tv.n)


def dump_lj_invalid_gcobj(o):
    return 'not valid type in GCobj @ {}'.format(strx64(o))


def dump_lj_invalid_tvalue(tv):
    return 'not valid type in TValue\'s GCobj @ {}'.format(strx64(gcval(tv)))


gcobj_dumpers = {
    'LJ_TSTR': dump_lj_tstr,
    'LJ_TUPVAL': dump_lj_tupval,
    'LJ_TTHREAD': dump_lj_tthread,
    'LJ_TPROTO': dump_lj_tproto,
    'LJ_TFUNC': dump_lj_tfunc,
    'LJ_TCDATA': dump_lj_tcdata,
    'LJ_TTAB': dump_lj_ttab,
    'LJ_TUDATA': dump_lj_tudata,
}

tvalue_dumpers = {
    'LJ_TNIL': dump_lj_tnil,
    'LJ_TFALSE': dump_lj_tfalse,
    'LJ_TTRUE': dump_lj_ttrue,
    'LJ_TLIGHTUD': dump_lj_tlightud,
    'LJ_TSTR': lambda tv: dump_lj_tstr(o=gcval(tv)),
    'LJ_TUPVAL': lambda tv: dump_lj_tupval(gcval(tv)),
    'LJ_TTHREAD': lambda tv: dump_lj_tthread(gcval(tv)),
    'LJ_TPROTO': lambda tv: dump_lj_tproto(gcval(tv)),
    'LJ_TFUNC': lambda tv: dump_lj_tfunc(gcval(tv)),
    'LJ_TTRACE': dump_lj_ttrace,
    'LJ_TCDATA': lambda tv: dump_lj_tcdata(gcval(tv)),
    'LJ_TTAB': lambda tv: dump_lj_ttab(gcval(tv)),
    'LJ_TUDATA': lambda tv: dump_lj_tudata(gcval(tv)),
    'LJ_TNUMX': dump_lj_tnumx,
}

LJ_T = {
    'NIL': i2notu32(0),
    'FALSE': i2notu32(1),
    'TRUE': i2notu32(2),
    'LIGHTUD': i2notu32(3),
    'STR': i2notu32(4),
    'UPVAL': i2notu32(5),
    'THREAD': i2notu32(6),
    'PROTO': i2notu32(7),
    'FUNC': i2notu32(8),
    'TRACE': i2notu32(9),
    'CDATA': i2notu32(10),
    'TAB': i2notu32(11),
    'UDATA': i2notu32(12),
    'NUMX': i2notu32(13),
}


def itypemap(o):
    if LJ_64 and not LJ_GC64:
        return (
            LJ_T['NUMX']
            if tvisnumber(o)
            else LJ_T['LIGHTUD'] if tvislightud(o) else itype(o)
        )
    else:
        return LJ_T['NUMX'] if tvisnumber(o) else itype(o)


def typenames(value):
    return {LJ_T[k]: 'LJ_T' + k for k in LJ_T.keys()}.get(int(value), 'LJ_TINVALID')


def dump_tvalue(tvptr):
    return tvalue_dumpers.get(typenames(itypemap(tvptr)), dump_lj_invalid_tvalue)(tvptr)


def dump_gcobj(o):
    return gcobj_dumpers.get(typenames(i2notu32(o.gch.gct)), dump_lj_invalid_gcobj)(o)


FRAME_TYPE = 0x3
FRAME_P = 0x4
FRAME_TYPEP = FRAME_TYPE | FRAME_P

FRAME = {
    'LUA': 0x0,  # Lua frame
    'C': 0x1,  # C frame
    'CONT': 0x2,  # Continuation frame
    'VARG': 0x3,  # Lua vararg frame
    'LUAP': 0x4,  # Lua protected frame (not documented?)
    'CP': 0x5,  # cpcall() frame
    'PCALL': 0x6,  # ff pcall() frame
    'PCALLH': 0x7,  # ff pcall() frame with active hook
}


def frametypes(ft):
    return {
        FRAME['LUA']: 'L',
        FRAME['C']: 'C',
        FRAME['CONT']: 'M',
        FRAME['VARG']: 'V',
    }.get(ft, '?')


def frametypeps(ftp):
    return {
        FRAME['LUA']: 'L',
        FRAME['C']: 'C',
        FRAME['CONT']: 'M',
        FRAME['VARG']: 'V',
        FRAME['LUAP']: 'LP',
        FRAME['CP']: 'CP',
        FRAME['PCALL']: 'PP',
        FRAME['PCALLH']: 'PPH',
    }.get(ftp, '?')


def bc_op(ins):
    return ins & 0xFF


def bc_a(ins):
    return (ins >> 8) & 0xFF


def frame_gc(framelink):
    return gcval(framelink - LJ_FR2)


def frame_ftsz(framelink):
    return vtou64(cast('ptrdiff_t', framelink.ftsz if LJ_FR2 else framelink.fr.tp.ftsz))


def frame_pc(framelink):
    return (
        cast(BCInsPtr, frame_ftsz(framelink))
        if LJ_FR2
        else mref(BCInsPtr, framelink.fr.tp.pcr)
    )


def frame_prevl(framelink):
    # We are evaluating the `frame_pc(framelink)[-1])` with lldb's
    # REPL, because the lldb API is faulty and it's not possible to cast
    # a struct member of 32-bit type to 64-bit type without getting onto
    # the next property bits, despite the fact that it's an actual value, not
    # a pointer to it.
    pc = frame_pc(framelink)

    # Invalid data
    # if not pc.value:
    # return None

    bcins = vtou64(dbg_eval('((BCIns *)' + str(pc) + ')[-1]'))

    # Test: is LLDB api faulty?
    new_bcins2 = (pc - 1).value.Dereference()
    assert (framelink - (1 + LJ_FR2 + bc_a(bcins))) == (
        framelink - (1 + LJ_FR2 + bc_a(new_bcins2.unsigned))
    )

    return framelink - (1 + LJ_FR2 + bc_a(bcins))


def frame_sized(framelink):
    return frame_ftsz(framelink) & ~FRAME_TYPEP


def frame_prevd(framelink):
    return framelink - int(frame_sized(framelink) / sizeof('TValue'))


def frame_type(framelink):
    return frame_ftsz(framelink) & FRAME_TYPE


def frame_typep(framelink):
    return frame_ftsz(framelink) & FRAME_TYPEP


def frame_islua(framelink):
    return frametypes(frame_type(framelink)) == 'L'


def frame_isc(framelink):
    return frametypes(frame_type(framelink)) == 'C'


def frame_isvarg(framelink):
    return frametypeps(frame_typep(framelink)) == 'V'


def frame_ispcall(framelink):
    return (frame_ftsz(framelink) & FRAME['PCALL']) == FRAME['PCALL']


def frame_prev(framelink):
    return frame_prevl(framelink) if frame_islua(framelink) else frame_prevd(framelink)


def frame_sentinel(L):
    return mref(TValuePtr, L.stack) + LJ_FR2


# The generator that implements frame iterator.
# Every frame is represented as a tuple of framelink and frametop.
def frames(L, limit):
    frametop = L.top
    framelink = L.base - 1
    nextframe = framelink
    framelink_sentinel = frame_sentinel(L)

    for _ in range(limit):
        yield framelink, frametop, nextframe

        if framelink <= framelink_sentinel:
            break

        frametop = framelink - (1 + LJ_FR2)
        nextframe = framelink
        framelink = frame_prev(framelink)

        # Invalid frame
        if not framelink:
            break


def dump_framelink_slot_address(fr):
    return (
        '{start:{padding}}:{end:{padding}}'.format(
            start=hex(int(fr - 1)),
            end=hex(int(fr)),
            padding=len(PADDING),
        )
        if LJ_FR2
        else '{addr:{padding}}'.format(
            addr=hex(int(fr)),
            padding=len(PADDING),
        )
    )


def format_lj_debug_getinfo(traceback):
    return ' [' + traceback + ']' if traceback else ''


def dump_framelink(L, level, fr, nextframe):
    if fr == frame_sentinel(L):
        return '{addr} [S   ] FRAME: dummy L, {thread}'.format(
            addr=dump_framelink_slot_address(fr), thread=dump_gcobj(frame_gc(fr))
        )
    return '{addr} [    ] FRAME #{level}: [{pp:<2}] delta={d}, {f}{traceback}'.format(
        addr=dump_framelink_slot_address(fr),
        level=level,
        pp=frametypeps(frame_typep(fr)),
        d=fr - frame_prev(fr),
        f=dump_gcobj(frame_gc(fr)),
        traceback=(
            format_lj_debug_getinfo(lj_debug_getinfo(L, fr - LJ_FR2, fr, nextframe))
            if not frame_isc(fr)
            and not frame_isvarg(
                nextframe
            )  # Not printing for C frames and for pseudo-frames
            else ''
        ),
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


def proto_varinfo(pt):
    return mref('uint8_t *', pt.varinfo)


def lj_buf_ruleb128(p, p_index):
    v = int(p[p_index])
    p_index += 1

    if v >= 0x80:
        sh = 0
        v &= 0x7F

        while True:
            sh += 7
            value = int(p[p_index])
            v |= (value & 0x7F) << sh

            p_index += 1
            if value < 0x80:
                break

    return v, p_index


def debug_varname(pt, pc, slot):
    p = lldb.value(proto_varinfo(pt))
    p_index = 0

    if not p:
        return None

    lastpc = 0

    while True:
        startpc, endpc = None, None
        name = p[p_index].sbvalue.address_of.summary
        vn = int(p[p_index])

        if vn < VARNAME__MAX:
            if vn == VARNAME_END:
                break  # End of varinfo.
        else:
            while int(p[p_index]) != 0:  # Skip over variable name.
                p_index += 1

        p_index += 1
        uleb128_result, p_index = lj_buf_ruleb128(p, p_index)
        lastpc = startpc = lastpc + uleb128_result

        if startpc > pc:
            break

        uleb128_result, p_index = lj_buf_ruleb128(p, p_index)
        endpc = startpc + uleb128_result

        if pc < endpc and slot == 0:
            if vn < VARNAME__MAX:
                return VARNAMES[vn - 1]

            return name

        slot -= 1

    return None


def debug_localname(L, frame, nextframe, slot):
    fn = cast(GCfuncCPtr, frame_gc(frame))
    name = None

    pc = debug_framepc(L, fn, nextframe)

    if frame == nextframe:  # nextframe is always valid in our debugger
        nextframe = L.top + LJ_FR2

    if frame_isvarg(nextframe):
        pt = funcproto(fn)

        if pt.flags & PROTO_VARARG:
            slot = pt.numparams + tou32(slot)

            if (frame + slot + LJ_FR2) < nextframe:
                return f'...[{slot}]'

        return name

    if pc != NO_BCPOS and (name := debug_varname(funcproto(fn), pc, slot - 1)):
        pass
    elif slot > 0 and (frame + slot + LJ_FR2) < nextframe:
        name = None  # In original code it's (*temporary), but it's not too useful for us

    return name


def format_localname(localname):
    return ' [local ' + localname + ']' if localname else ''


def dump_stack(L, base=None, top=None):
    if not L:
        return 'Main coroutine not found. Provide an address of lua_State*'

    base = base or L.base
    top = top or L.top

    global PADDING
    if not PADDING:
        PADDING = ' ' * len(strx64((TValuePtr(L.addr))))

    stack = mref(TValuePtr, L.stack)
    maxstack = mref(TValuePtr, L.maxstack)
    frame_stack_size = int((maxstack - stack) >> 3)
    red = 5 + 2 * LJ_FR2

    dump = [
        '{padding} Red zone: {nredslots: >2} slots {padding}'.format(
            padding='-' * len(PADDING),
            nredslots=red,
        ),
    ]
    dump.extend(
        [
            dump_stack_slot(L, maxstack + offset, base, top)
            for offset in range(red, 0, -1)  # noqa: E131
        ]
    )
    dump.extend(
        [
            '{padding} Stack: {nstackslots: >5} slots {padding}'.format(
                padding='-' * len(PADDING),
                nstackslots=frame_stack_size,
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
        ]
    )

    level = 0

    for framelink, frametop, nextframe in frames(L, frame_stack_size):
        # Dump all data slots in the (framelink, top) interval.
        dump.extend(
            [
                dump_stack_slot(L, framelink + offset, base, top)
                + format_localname(
                    debug_localname(
                        L,
                        framelink,
                        nextframe,
                        offset,
                    )
                )
                for offset in range(frametop - framelink, 0, -1)  # noqa: E131
            ]
        )
        # Dump frame slot (2 slots in case of GC64).
        dump.append(dump_framelink(L, level, framelink, nextframe))

        # Next frame is a pseudo-frame of the current vararg frame, it has the same level.
        if not frame_isvarg(framelink):
            level += 1

    return '\n'.join(dump)


class LJDumpGCobj(Command):
    '''
lj-gcobj <GCobj *>
    '''

    def execute(self, debugger, args, result):
        gcobj_ptr = cast(GCobjPtr, self.parse(args))
        print(dump_gcobj(gcobj_ptr))


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

    def execute(self, debugger, args, result):
        tvptr = cast(TValuePtr, self.parse(args))
        print(dump_tvalue(tvptr))


class LJState(Command):
    '''
lj-state
The command requires no args and dumps current VM and GC states
* VM state: <INTERP|C|GC|EXIT|RECORD|OPT|ASM|TRACE>
* GC state: <PAUSE|PROPAGATE|ATOMIC|SWEEPSTRING|SWEEP|FINALIZE|LAST>
* JIT state: <IDLE|ACTIVE|RECORD|START|END|ASM|ERR>
    '''
    def execute(self, debugger, args, result):
        g = G(L(None))
        print(
            '{}'.format(
                '\n'.join(
                    map(
                        lambda t: '{} state: {}'.format(*t),
                        {
                            'VM': vm_state(g),
                            'GC': gc_state(g),
                            'JIT': jit_state(g),
                        }.items(),
                    )
                )
            )
        )


class LJDumpArch(Command):
    '''
lj-arch

The command requires no args and dumps values of LJ_64 and LJ_GC64
compile-time flags. These values define the sizes of host and GC
pointers respectively.
    '''
    def execute(self, debugger, args, result):
        print(
            'LJ_64: {LJ_64}, LJ_GC64: {LJ_GC64}, LJ_DUALNUM: {LJ_DUALNUM}'.format(
                LJ_64=LJ_64, LJ_GC64=LJ_GC64, LJ_DUALNUM=LJ_DUALNUM
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
    def execute(self, debugger, args, result):
        g = G(L(None))
        print('GC stats: {state}\n{stats}'.format(state=gc_state(g), stats=dump_gc(g)))


class LJDumpString(Command):
    '''
lj-str <GCstr *>

The command receives a <gcr> of the corresponding GCstr object and dumps
the payload, size in bytes and hash.

*Caveat*: Since Python 2 provides no native Unicode support, the payload
is replaced with the corresponding error when decoding fails.
    '''
    def execute(self, debugger, args, result):
        string_ptr = cast(GCstrPtr, self.parse(args))
        print(
            'String: {body} [{len} bytes] with hash {hash}'.format(
                body=strdata(string_ptr),
                hash=strx64(string_ptr.hash),
                len=string_ptr.len,
            )
        )


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

    def execute(self, debugger, args, result):
        t = cast(GCtabPtr, self.parse(args))
        array = mref(TValuePtr, t.array)
        nodes = mref(NodePtr, t.node)
        mt = gcref(t.metatable)
        capacity = {
            'apart': int(t.asize),
            'hpart': int(t.hmask + 1) if t.hmask > 0 else 0,
        }

        if mt:
            print('Metatable detected: {}'.format(strx64(mt)))

        print('Array part: {} slots'.format(capacity['apart']))
        for i in range(capacity['apart']):
            slot = array + i
            print(
                '{ptr}: [{index}]: {value}'.format(
                    ptr=strx64(slot), index=i, value=dump_tvalue(slot)
                )
            )

        print('Hash part: {} nodes'.format(capacity['hpart']))
        # See hmask comment in lj_obj.h
        for i in range(capacity['hpart']):
            node = nodes + i
            print(
                '{ptr}: {{ {key} }} => {{ {val} }}; next = {n}'.format(
                    ptr=strx64(node),
                    key=dump_tvalue(TValuePtr(node.key.addr)),
                    val=dump_tvalue(TValuePtr(node.val.addr)),
                    n=strx64(mref(NodePtr, node.next)),
                )
            )


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
    + LP: Lua protected frame (not documented?)
    + CP: Protected C frame
    + PP: VM performs a call as a result of executinig pcall or xpcall

If L is omitted the main coroutine is used.
    '''

    def execute(self, debugger, args, result):
        lstate = self.parse(args)
        lstate_ptr = cast('lua_State *', lstate) if lstate is not None else None

        print('{}'.format(dump_stack(L(lstate_ptr))))


def register_commands(debugger, commands):
    for command, cls in commands.items():
        cls.command = command
        debugger.HandleCommand(
            'command script add --overwrite --class luajit_lldb.{cls} {cmd}'.format(
                cls=cls.__name__,
                cmd=cls.command,
            )
        )
        print('{cmd} command intialized'.format(cmd=cls.command))


# Searching for luajit information using luaL_newstate. It's expected to be the only one.
def find_luajit_module():
    for s in target.FindSymbols('luaL_newstate'):
        if s.symbol.addr:
            return s.module

    return None


def configure(debugger):
    global LJ_64, LJ_GC64, LJ_FR2, LJ_DUALNUM, PADDING, LJ_TISNUM, target, luajit_module
    target = debugger.GetSelectedTarget()
    luajit_module = find_luajit_module()

    LJ_DUALNUM = luajit_module.FindSymbol('lj_lib_checknumber') is not None

    try:
        irtype_enum = find_type('IRType').enum_members
        for member in irtype_enum:
            if member.name == 'IRT_PTR':
                LJ_64 = member.unsigned & 0x1F == IRT_P64
            if member.name == 'IRT_PGC':
                LJ_FR2 = LJ_GC64 = member.unsigned & 0x1F == IRT_P64
    except Exception:
        print('luajit_lldb.py failed to load: '
              'no debugging symbols found for libluajit')
        return

    PADDING = ' ' * len(strx64((TValuePtr(L().addr)))) if L() else None
    LJ_TISNUM = 0xFFFEFFFF if LJ_64 and not LJ_GC64 else LJ_T['NUMX']


def __lldb_init_module(debugger, internal_dict):
    try:
        configure(debugger)
        register_commands(
            debugger,
            {
                'lj-tv': LJDumpTValue,
                'lj-state': LJState,
                'lj-arch': LJDumpArch,
                'lj-gc': LJGC,
                'lj-gcobj': LJDumpGCobj,
                'lj-str': LJDumpString,
                'lj-tab': LJDumpTable,
                'lj-stack': LJDumpStack,
            },
        )
        print('luajit_lldb.py is successfully loaded')
    except Exception as e:
        import traceback

        # `e` is an exception object that you get from somewhere
        print(e, ''.join(traceback.format_tb(e.__traceback__)))
