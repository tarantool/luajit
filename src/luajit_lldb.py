# LLDB extension for LuaJIT post-mortem analysis.
# To use, just put 'command script import <path-to-repo>/src/luajit_lldb.py'
# in lldb.

import abc
import re
import lldb
import struct

LJ_64 = None
LJ_GC64 = None
LJ_FR2 = None
LJ_DUALNUM = None
PADDING = None

# Constants
IRT_P64 = 9
LJ_GCVMASK = ((1 << 47) - 1)
LJ_TISNUM = None

# These constants are meaningful only for 'LJ_64' mode.
LJ_LIGHTUD_BITS_SEG = 8
LJ_LIGHTUD_BITS_LO = 47 - LJ_LIGHTUD_BITS_SEG
LIGHTUD_SEG_MASK = (1 << LJ_LIGHTUD_BITS_SEG) - 1
LIGHTUD_LO_MASK = (1 << LJ_LIGHTUD_BITS_LO) - 1

# Debugger specific {{{


# Global
target = None


def lldb_tp_isfp(tp):
    return tp.GetBasicType() in [
        lldb.eBasicTypeFloat,
        lldb.eBasicTypeDouble,
        lldb.eBasicTypeLongDouble
    ]


def lldb_value_from_raw(raw_value, size, tp):
    isfp = lldb_tp_isfp(tp)
    pack_flag = '<d' if isfp else '<Q'
    raw_data = struct.pack(pack_flag, raw_value)
    sbdata = lldb.SBData()
    sbdata.SetData(
        lldb.SBError(),
        raw_data,
        lldb.eByteOrderLittle,
        size
    )
    sbval_res = target.CreateValueFromData(
        # XXX: The name is required. Let's make it meaningful.
        '({tp}){val}'.format(
            tp=tp.name,
            val=raw_value if isfp else hex(raw_value)
        ),
        sbdata,
        tp
    )
    return lldb.value(sbval_res)


def lldb__add__(self, other):
    other = int(other)
    sbvalue = self.sbvalue
    if sbvalue.TypeIsPointerType():
        tp = sbvalue.GetType()
        sz = sbvalue.deref.size
        addr = sbvalue.GetValueAsUnsigned() + other * sz
        return lldb_value_from_raw(addr, sbvalue.GetByteSize(), tp)
    else:
        return int(self) + other


def lldb__bool__(self):
    return int(self) != 0


def lldb__ge__(self, other):
    return int(self) >= int(other)


def lldb__getitem__(self, key):
    if type(key) is lldb.value:
        key = int(key)
    if type(key) is int:
        # Allow array access.
        return lldb.value(self.sbvalue.GetValueForExpressionPath('[%i]' % key))
    elif type(key) is str:
        return lldb.value(self.sbvalue.GetChildMemberWithName(key))
    raise Exception(TypeError('No item of type %s' % str(type(key))))


def lldb__gt__(self, other):
    return int(self) > int(other)


def lldb__le__(self, other):
    return int(self) <= int(other)


def lldb__lt__(self, other):
    return int(self) < int(other)


def lldb__str__(self):
    # Instead of default GetSummary.
    if not self.sbvalue.TypeIsPointerType():
        tp = self.sbvalue.GetType()
        is_float = lldb_tp_isfp(tp)
        if is_float:
            return self.sbvalue.GetValue()
        else:
            return str(int(self))

    s = self.sbvalue.GetValue()
    if s[:2] == '0x':
        # Strip useless leading zeros.
        res = s[2:].lstrip('0')
        return '0x' + (res if res else '0')
    return s


def lldb__sub__(self, other):
    if type(other) is not lldb.value or \
       type(other) is lldb.value and not other.sbvalue.TypeIsPointerType():
        other = int(other)
    if type(other) is int:
        return lldb__add__(self, -other)
    elif self.sbvalue.TypeIsPointerType():
        ssbval = self.sbvalue
        osbval = other.sbvalue
        self_tp = ssbval.GetType()
        other_tp = osbval.GetType()
        # Subtract pointers of the same size only.
        elsz = self_tp.GetDereferencedType().size
        if other_tp.GetDereferencedType().size != elsz:
            raise Exception('Attempt to substruct {otp} from {stp}'.format(
                stp=self_tp.name,
                otp=other_tp.name
            ))
        diff = ssbval.GetValueAsUnsigned() - osbval.GetValueAsUnsigned()
        return int(diff / elsz)
    else:
        return int(self) - int(other)


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

    @abc.abstractproperty
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


gtype_cache = {}


def gtype(typestr):
    if typestr in gtype_cache:
        return gtype_cache[typestr]

    m = re.match(r'((?:(?:struct|union) )?\S*)\s*[*]', typestr)

    gtype = target.FindFirstType(typestr) if m is None \
        else target.FindFirstType(m.group(1)).GetPointerType()

    gtype_cache[typestr] = gtype
    return gtype


def cast(typestr, val):
    if isinstance(val, lldb.value):
        val = val.sbvalue
    elif type(val) is int:
        tp = gtype(typestr)
        return lldb_value_from_raw(val, tp.GetByteSize(), tp)
    elif not isinstance(val, lldb.SBValue):
        raise Exception('unexpected cast from type: {t}'.format(t=type(val)))

    # XXX: Simply SBValue.Cast() works incorrectly since it may
    # take the 8 bytes of memory instead of 4, before the cast.
    # Construct the value on the fly.
    tp = gtype(typestr)
    is_fp = lldb_tp_isfp(tp)
    rawval = float(val.GetValue()) if is_fp else val.GetValueAsUnsigned()
    return lldb_value_from_raw(rawval, val.GetByteSize(), tp)


def lookup_global(name):
    return target.FindFirstGlobalVariable(name)


def type_member(type_obj, name):
    return next((x for x in type_obj.members if x.name == name), None)


def offsetof(typename, membername):
    type_obj = gtype(typename)
    member = type_member(type_obj, membername)
    assert member is not None
    return member.GetOffsetInBytes()


def sizeof(typename):
    type_obj = gtype(typename)
    return type_obj.GetByteSize()


def tou64(val):
    return cast('uint64_t', val) & 0xFFFFFFFFFFFFFFFF


def dbg_eval(expr):
    process = target.GetProcess()
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()
    return frame.EvaluateExpression(expr)


# }}} Debugger specific


def gcval(obj):
    return cast('GCobj *', obj['gcptr64'] & LJ_GCVMASK if LJ_GC64
                else cast('uintptr_t', obj['gcptr32']))


def gcref(obj):
    return cast('GCobj *', obj['gcptr64'] if LJ_GC64
                else cast('uintptr_t', obj['gcptr32']))


def gcnext(obj):
    return gcref(obj)['gch']['nextgc']


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


def dump_gc(g):
    gc = g['gc']
    stats = ['{key}: {value}'.format(key=f, value=getattr(gc, f)) for f in (
        'total', 'threshold', 'debt', 'estimate', 'stepmul', 'pause'
    )]

    stats += ['sweepstr: {sweepstr}/{strmask}'.format(
        sweepstr=gc['sweepstr'],
        # String hash mask (size of hash table - 1).
        strmask=g['strmask'] + 1,
    )]

    stats += ['{key}: {number} objects'.format(
        key=stat,
        number=handler(getattr(gc, stat))
    ) for stat, handler in gclen.items()]
    return '\n'.join(map(lambda s: '\t' + s, stats))


def mref(typename, obj):
    return cast(typename, obj['ptr64'] if LJ_GC64 else obj['ptr32'])


def J(g):
    g_offset = offsetof('GG_State', 'g')
    J_offset = offsetof('GG_State', 'J')
    return cast('jit_State *', (cast('char *', g) - g_offset + J_offset))


def G(L):
    return mref('global_State *', L['glref'])


def L(L=None):
    # lookup a symbol for the main coroutine considering the host app
    # XXX Fragile: though the loop initialization looks like a crap but it
    # respects both Python 2 and Python 3.
    for lstate in [L] + list(map(lambda main: lookup_global(main), (
        # LuaJIT main coro (see luajit/src/luajit.c)
        'globalL',
        # Tarantool main coro (see tarantool/src/lua/init.h)
        'tarantool_L',
        # TODO: Add more
    ))):
        if lstate:
            return cast('lua_State *', lstate)


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
    }.get(int(J(g).state), 'INVALID')


def strx64(val):
    return re.sub('L?$', '',
                  hex(int(cast('uint64_t', val) & 0xFFFFFFFFFFFFFFFF)))


def funcproto(func):
    assert func.ffid == 0
    return cast('GCproto *', mref('char *', func.pc) - sizeof('GCproto'))


def strdata(obj):
    try:
        ptr = cast('char *', cast('GCstr *', obj) + 1)
        return ptr.sbvalue.summary
    except UnicodeEncodeError:
        return "<luajit-lldb: error occurred while rendering non-ascii slot>"


def itype(o):
    return tou32(o['it64'] >> 47) if LJ_GC64 else o['it']


def tvisint(o):
    return LJ_DUALNUM and itype(o) == LJ_TISNUM


def tvislightud(o):
    if LJ_64 and not LJ_GC64:
        return (int(cast('int32_t', itype(o))) >> 15) == -2
    else:
        return itype(o) == LJ_T['LIGHTUD']


def tvisnumber(o):
    return itype(o) <= LJ_TISNUM


def lightudV(tv):
    if LJ_64:
        u = int(tv['u64'])
        # lightudseg macro expanded.
        seg = (u >> LJ_LIGHTUD_BITS_LO) & LIGHTUD_SEG_MASK
        segmap = mref('uint32_t *', G(L(None))['gc']['lightudseg'])
        # lightudlo macro expanded.
        return (int(segmap[seg]) << 32) | (u & LIGHTUD_LO_MASK)
    else:
        return gcval(tv['gcr'])


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
        body=strdata(cast('GCstr *', gcval(tv['gcr']))),
        address=strx64(gcval(tv['gcr']))
    )


def dump_lj_tupval(tv):
    return 'upvalue @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tthread(tv):
    return 'thread @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tproto(tv):
    return 'proto @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tfunc(tv):
    func = cast('GCfuncC *', gcval(tv['gcr']))
    ffid = func['ffid']

    if ffid == 0:
        pt = funcproto(func)
        return 'Lua function @ {addr}, {nups} upvalues, {chunk}:{line}'.format(
            addr=strx64(func),
            nups=func['nupvalues'],
            chunk=strdata(cast('GCstr *', gcval(pt['chunkname']))),
            line=pt['firstline']
        )
    elif ffid == 1:
        return 'C function @ {}'.format(strx64(func['f']))
    else:
        return 'fast function #{}'.format(ffid)


def dump_lj_ttrace(tv):
    trace = cast('GCtrace *', gcval(tv['gcr']))
    return 'trace {traceno} @ {addr}'.format(
        traceno=strx64(trace['traceno']),
        addr=strx64(trace)
    )


def dump_lj_tcdata(tv):
    return 'cdata @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_ttab(tv):
    table = cast('GCtab *', gcval(tv['gcr']))
    return 'table @ {gcr} (asize: {asize}, hmask: {hmask})'.format(
        gcr=strx64(table),
        asize=table['asize'],
        hmask=strx64(table['hmask']),
    )


def dump_lj_tudata(tv):
    return 'userdata @ {}'.format(strx64(gcval(tv['gcr'])))


def dump_lj_tnumx(tv):
    if tvisint(tv):
        return 'integer {}'.format(cast('int32_t', tv['i']))
    else:
        return 'number {}'.format(cast('double', tv['n']))


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


def dump_tvalue(tvalue):
    return dumpers.get(typenames(itypemap(tvalue)), dump_lj_invalid)(tvalue)


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
    return cast('ptrdiff_t', framelink['ftsz'] if LJ_FR2
                else framelink['fr']['tp']['ftsz'])


def frame_pc(framelink):
    return cast('BCIns *', frame_ftsz(framelink)) if LJ_FR2 \
        else mref('BCIns *', framelink['fr']['tp']['pcr'])


def frame_prevl(framelink):
    return framelink - (1 + LJ_FR2 + bc_a(frame_pc(framelink)[-1]))


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
        d=cast('TValue *', fr) - cast('TValue *', frame_prev(fr)),
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
        tvptr = cast('TValue *', self.parse(args))
        print('{}'.format(dump_tvalue(tvptr)))


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
        print('{}'.format('\n'.join(
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
    def execute(self, debugger, args, result):
        print(
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
    def execute(self, debugger, args, result):
        g = G(L(None))
        print('GC stats: {state}\n{stats}'.format(
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
    def execute(self, debugger, args, result):
        string = cast('GCstr *', self.parse(args))
        print("String: {body} [{len} bytes] with hash {hash}".format(
            body=strdata(string),
            hash=strx64(string['hash']),
            len=string['len'],
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
    def execute(self, debugger, args, result):
        t = cast('GCtab *', self.parse(args))
        array = mref('TValue *', t['array'])
        nodes = mref('Node *', t['node'])
        mt = gcval(t['metatable'])
        capacity = {
            'apart': int(t['asize']),
            'hpart': int(t['hmask'] + 1) if t['hmask'] > 0 else 0
        }

        if mt:
            print('Metatable detected: {}'.format(strx64(mt)))

        print('Array part: {} slots'.format(capacity['apart']))
        for i in range(capacity['apart']):
            slot = array + i
            print('{ptr}: [{index}]: {value}'.format(
                ptr=strx64(slot),
                index=i,
                value=dump_tvalue(slot)
            ))

        print('Hash part: {} nodes'.format(capacity['hpart']))
        # See hmask comment in lj_obj.h
        for i in range(capacity['hpart']):
            node = nodes + i
            print('{ptr}: {{ {key} }} => {{ {val} }}; next = {n}'.format(
                ptr=strx64(node),
                key=dump_tvalue(node['key']),
                val=dump_tvalue(node['val']),
                n=strx64(mref('Node *', node['next']))
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
    def execute(self, debugger, args, result):
        print('{}'.format(dump_stack(L(self.parse(args)))))


def register_commands(debugger, commands):
    for command, cls in commands.items():
        cls.command = command
        debugger.HandleCommand(
            'command script add --overwrite --class luajit_lldb.{cls} {cmd}'
            .format(
                cls=cls.__name__,
                cmd=cls.command,
            )
        )
        print('{cmd} command initialized'.format(cmd=cls.command))


def configure(debugger):
    global LJ_64, LJ_GC64, LJ_FR2, LJ_DUALNUM, PADDING, LJ_TISNUM, target
    target = debugger.GetSelectedTarget()
    module = target.modules[0]
    LJ_DUALNUM = module.FindSymbol('lj_lib_checknumber') is not None

    try:
        irtype_enum = target.FindFirstType('IRType').enum_members
        for member in irtype_enum:
            if member.name == 'IRT_PTR':
                LJ_64 = member.unsigned & 0x1f == IRT_P64
            if member.name == 'IRT_PGC':
                LJ_FR2 = LJ_GC64 = member.unsigned & 0x1f == IRT_P64
    except Exception:
        print('luajit_lldb.py failed to load: '
              'no debugging symbols found for libluajit')
        return

    PADDING = ' ' * len(':' + hex((1 << (47 if LJ_GC64 else 32)) - 1))
    LJ_TISNUM = 0xfffeffff if LJ_64 and not LJ_GC64 else LJ_T['NUMX']


def __lldb_init_module(debugger, internal_dict):
    configure(debugger)
    register_commands(debugger, {
        'lj-arch':  LJDumpArch,
        'lj-gc':    LJGC,
        'lj-stack': LJDumpStack,
        'lj-state': LJState,
        'lj-str':   LJDumpString,
        'lj-tab':   LJDumpTable,
        'lj-tv':    LJDumpTValue,
    })
    print('luajit_lldb.py is successfully loaded')
