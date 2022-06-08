# GDB extension for LuaJIT post-mortem analysis.
# To use, just put 'source <path-to-repo>/src/luajit-gdb.py' in gdb.

import re
import gdb
import sys

# make script compatible with the ancient Python {{{

LEGACY = re.match(r'^2\.', sys.version)

if LEGACY:
    CONNECTED = False
    int = long
    range = xrange

# }}}

gtype_cache = {}

def gtype(typestr):
    global gtype_cache
    if typestr in gtype_cache:
        return gtype_cache[typestr]

    m = re.match(r'((?:(?:struct|union) )?\S*)\s*[*]', typestr)

    gtype = gdb.lookup_type(typestr) if m is None \
        else gdb.lookup_type(m.group(1)).pointer()

    gtype_cache[typestr] = gtype
    return gtype

def cast(typestr, val):
    return gdb.Value(val).cast(gtype(typestr))

def lookup(symbol):
    variable, _ = gdb.lookup_symbol(symbol)
    return variable.value() if variable else None

def parse_arg(arg):
    if not arg:
        return None

    ret = gdb.parse_and_eval(arg)

    if not ret:
        raise gdb.GdbError('table argument empty')

    return ret

def tou64(val):
    return cast('uint64_t', val) & 0xFFFFFFFFFFFFFFFF

def tou32(val):
    return cast('uint32_t', val) & 0xFFFFFFFF

def i2notu32(val):
    return ~int(val) & 0xFFFFFFFF

def strx64(val):
    return re.sub('L?$', '',
                  hex(int(cast('uint64_t', val) & 0xFFFFFFFFFFFFFFFF)))

# Types {{{

LJ_T = {
    'NIL'     : i2notu32(0),
    'FALSE'   : i2notu32(1),
    'TRUE'    : i2notu32(2),
    'LIGHTUD' : i2notu32(3),
    'STR'     : i2notu32(4),
    'UPVAL'   : i2notu32(5),
    'THREAD'  : i2notu32(6),
    'PROTO'   : i2notu32(7),
    'FUNC'    : i2notu32(8),
    'TRACE'   : i2notu32(9),
    'CDATA'   : i2notu32(10),
    'TAB'     : i2notu32(11),
    'UDATA'   : i2notu32(12),
    'NUMX'    : i2notu32(13),
}

def typenames(value):
    return {
        LJ_T[k]: 'LJ_T' + k for k in LJ_T.keys()
    }.get(int(value), 'LJ_TINVALID')

# }}}

# Frames {{{

FRAME_TYPE = 0x3
FRAME_P = 0x4
FRAME_TYPEP = FRAME_TYPE | FRAME_P

FRAME = {
    'LUA': 0x0,
    'C': 0x1,
    'CONT': 0x2,
    'VARG': 0x3,
    'LUAP': 0x4,
    'CP': 0x5,
    'PCALL': 0x6,
    'PCALLH': 0x7,
}

def frametypes(ft):
    return {
        FRAME['LUA']  : 'L',
        FRAME['C']    : 'C',
        FRAME['CONT'] : 'M',
        FRAME['VARG'] : 'V',
    }.get(ft, '?')

def bc_op(ins):
    return int(ins) & 0xff

def bc_a(ins):
    return (int(ins) >> 8) & 0xff

def bc_b(ins):
    return int(ins) >> 24

def bc_c(ins):
    return (int(ins) >> 16) & 0xff

def bc_d(ins):
    return int(ins) >> 16

___ = 0

BYTECODES = [
    # Comparison ops. ORDER OPR.
    {'name': 'ISLT',   'ra': 'var',   'rb': ___,     'rcd': 'var',   'mm': 'lt'},
    {'name': 'ISGE',   'ra': 'var',   'rb': ___,     'rcd': 'var',   'mm': 'lt'},
    {'name': 'ISLE',   'ra': 'var',   'rb': ___,     'rcd': 'var',   'mm': 'le'},
    {'name': 'ISGT',   'ra': 'var',   'rb': ___,     'rcd': 'var',   'mm': 'le'},

    {'name': 'ISEQV',  'ra': 'var',   'rb': ___,     'rcd': 'var',   'mm': 'eq'},
    {'name': 'ISNEV',  'ra': 'var',   'rb': ___,     'rcd': 'var',   'mm': 'eq'},
    {'name': 'ISEQS',  'ra': 'var',   'rb': ___,     'rcd': 'str',   'mm': 'eq'},
    {'name': 'ISNES',  'ra': 'var',   'rb': ___,     'rcd': 'str',   'mm': 'eq'},
    {'name': 'ISEQN',  'ra': 'var',   'rb': ___,     'rcd': 'num',   'mm': 'eq'},
    {'name': 'ISNEN',  'ra': 'var',   'rb': ___,     'rcd': 'num',   'mm': 'eq'},
    {'name': 'ISEQP',  'ra': 'var',   'rb': ___,     'rcd': 'pri',   'mm': 'eq'},
    {'name': 'ISNEP',  'ra': 'var',   'rb': ___,     'rcd': 'pri',   'mm': 'eq'},

    # Unary test and copy ops.
    {'name': 'ISTC',   'ra': 'dst',   'rb': ___,     'rcd': 'var',   'mm': ___},
    {'name': 'ISFC',   'ra': 'dst',   'rb': ___,     'rcd': 'var',   'mm': ___},
    {'name': 'IST',    'ra': ___,     'rb': ___,     'rcd': 'var',   'mm': ___},
    {'name': 'ISF',    'ra': ___,     'rb': ___,     'rcd': 'var',   'mm': ___},
    {'name': 'ISTYPE', 'ra': 'var',   'rb': ___,     'rcd': 'lit',   'mm': ___},
    {'name': 'ISNUM',  'ra': 'var',   'rb': ___,     'rcd': 'lit',   'mm': ___},
    {'name': 'MOV',    'ra': 'dst',   'rb': ___,     'rcd': 'var',   'mm': ___},
    {'name': 'NOT',    'ra': 'dst',   'rb': ___,     'rcd': 'var',   'mm': ___},
    {'name': 'UNM',    'ra': 'dst',   'rb': ___,     'rcd': 'var',   'mm': 'unm'},
    {'name': 'LEN',    'ra': 'dst',   'rb': ___,     'rcd': 'var',   'mm': 'len'},
    {'name': 'ADDVN',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'add'},
    {'name': 'SUBVN',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'sub'},
    {'name': 'MULVN',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'mul'},
    {'name': 'DIVVN',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'div'},
    {'name': 'MODVN',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'mod'},

    # Binary ops. ORDER OPR.
    {'name': 'ADDNV',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'add'},
    {'name': 'SUBNV',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'sub'},
    {'name': 'MULNV',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'mul'},
    {'name': 'DIVNV',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'div'},
    {'name': 'MODNV',  'ra': 'dst',   'rb': 'var',   'rcd': 'num',   'mm': 'mod'},

    {'name': 'ADDVV',  'ra': 'dst',   'rb': 'var',   'rcd': 'var',   'mm': 'add'},
    {'name': 'SUBVV',  'ra': 'dst',   'rb': 'var',   'rcd': 'var',   'mm': 'sub'},
    {'name': 'MULVV',  'ra': 'dst',   'rb': 'var',   'rcd': 'var',   'mm': 'mul'},
    {'name': 'DIVVV',  'ra': 'dst',   'rb': 'var',   'rcd': 'var',   'mm': 'div'},
    {'name': 'MODVV',  'ra': 'dst',   'rb': 'var',   'rcd': 'var',   'mm': 'mod'},

    {'name': 'POW',    'ra': 'dst',   'rb': 'var',   'rcd': 'var',   'mm': 'pow'},
    {'name': 'CAT',    'ra': 'dst',   'rb': 'rbase', 'rcd': 'rbase', 'mm': 'concat'},

    # Constant ops.
    {'name': 'KSTR',   'ra': 'dst',   'rb':  ___,    'rcd': 'str',   'mm': ___},
    {'name': 'KCDATA', 'ra': 'dst',   'rb':  ___,    'rcd': 'cdata', 'mm': ___},
    {'name': 'KSHORT', 'ra': 'dst',   'rb':  ___,    'rcd': 'lits',  'mm': ___},
    {'name': 'KNUM',   'ra': 'dst',   'rb':  ___,    'rcd': 'num',   'mm': ___},
    {'name': 'KPRI',   'ra': 'dst',   'rb':  ___,    'rcd': 'pri',   'mm': ___},
    {'name': 'KNIL',   'ra': 'base',  'rb':  ___,    'rcd': 'base',  'mm': ___},

    # Upvalue and function ops.
    {'name': 'UGET',   'ra': 'dst',   'rb':  ___,    'rcd':  'uv',   'mm':  ___},
    {'name': 'USETV',  'ra': 'uv',    'rb':  ___,    'rcd':  'var',  'mm':  ___},
    {'name': 'USETS',  'ra': 'uv',    'rb':  ___,    'rcd':  'str',  'mm':  ___},
    {'name': 'USETN',  'ra': 'uv',    'rb':  ___,    'rcd':  'num',  'mm':  ___},
    {'name': 'USETP',  'ra': 'uv',    'rb':  ___,    'rcd':  'pri',  'mm':  ___},
    {'name': 'UCLO',   'ra': 'rbase', 'rb':  ___,    'rcd':  'jump', 'mm':  ___},
    {'name': 'FNEW',   'ra': 'dst',   'rb':  ___,    'rcd':  'func', 'mm':  ___},

    # Table ops.
    {'name': 'TNEW',   'ra': 'dst',   'rb':  ___,    'rcd': 'lit',   'mm': ___},
    {'name': 'TDUP',   'ra': 'dst',   'rb':  ___,    'rcd': 'tab',   'mm': ___},
    {'name': 'GGET',   'ra': 'dst',   'rb':  ___,    'rcd': 'str',   'mm': 'index'},
    {'name': 'GSET',   'ra': 'var',   'rb':  ___,    'rcd': 'str',   'mm': 'newindex'},
    {'name': 'TGETV',  'ra': 'dst',   'rb':  'var',  'rcd': 'var',   'mm': 'index'},
    {'name': 'TGETS',  'ra': 'dst',   'rb':  'var',  'rcd': 'str',   'mm': 'index'},
    {'name': 'TGETB',  'ra': 'dst',   'rb':  'var',  'rcd': 'lit',   'mm': 'index'},
    {'name': 'TGETR',  'ra': 'dst',   'rb':  'var',  'rcd': 'var',   'mm': 'index'},
    {'name': 'TSETV',  'ra': 'var',   'rb':  'var',  'rcd': 'var',   'mm': 'newindex'},
    {'name': 'TSETS',  'ra': 'var',   'rb':  'var',  'rcd': 'str',   'mm': 'newindex'},
    {'name': 'TSETB',  'ra': 'var',   'rb':  'var',  'rcd': 'lit',   'mm': 'newindex'},
    {'name': 'TSETM',  'ra': 'base',  'rb':  ___,    'rcd': 'num',   'mm': 'newindex'},
    {'name': 'TSETR',  'ra': 'var',   'rb':  'var',  'rcd': 'var',   'mm': 'newindex'},

    # Calls and vararg handling. T = tail call.
    {'name': 'CALLM',  'ra': 'base',  'rb':  'lit',  'rcd': 'lit',   'mm': 'call'},
    {'name': 'CALL',   'ra': 'base',  'rb':  'lit',  'rcd': 'lit',   'mm': 'call'},
    {'name': 'CALLMT', 'ra': 'base',  'rb':  ___,    'rcd': 'lit',   'mm': 'call'},
    {'name': 'CALLT',  'ra': 'base',  'rb':  ___,    'rcd': 'lit',   'mm': 'call'},
    {'name': 'ITERC',  'ra': 'base',  'rb':  'lit',  'rcd': 'lit',   'mm': 'call'},
    {'name': 'ITERN',  'ra': 'base',  'rb':  'lit',  'rcd': 'lit',   'mm': 'call'},
    {'name': 'VARG',   'ra': 'base',  'rb':  'lit',  'rcd': 'lit',   'mm': ___},
    {'name': 'ISNEXT', 'ra': 'base',  'rb':  ___,    'rcd': 'jump',  'mm': ___},

    # Returns.
    {'name': 'RETM',   'ra': 'base',  'rb':  ___,    'rcd': 'lit',   'mm': ___},
    {'name': 'RET',    'ra': 'rbase', 'rb':  ___,    'rcd': 'lit',   'mm': ___},
    {'name': 'RET0',   'ra': 'rbase', 'rb':  ___,    'rcd': 'lit',   'mm': ___},
    {'name': 'RET1',   'ra': 'rbase', 'rb':  ___,    'rcd': 'lit',   'mm': ___},

    # Loops and branches. I/J = interp/JIT, I/C/L = init/call/loop.
    {'name': 'FORI',   'ra': 'base',  'rb':  ___,    'rcd': 'jump',  'mm': ___},
    {'name': 'JFORI',  'ra': 'base',  'rb':  ___,    'rcd': 'jump',  'mm': ___},

    {'name': 'FORL',   'ra': 'base',  'rb':  ___,    'rcd': 'jump',  'mm': ___},
    {'name': 'IFORL',  'ra': 'base',  'rb':  ___,    'rcd': 'jump',  'mm': ___},
    {'name': 'JFORL',  'ra': 'base',  'rb':  ___,    'rcd': 'lit',   'mm': ___},

    {'name': 'ITERL',  'ra': 'base',  'rb':  ___,    'rcd': 'jump',  'mm': ___},
    {'name': 'IITERL', 'ra': 'base',  'rb':  ___,    'rcd': 'jump',  'mm': ___},
    {'name': 'JITERL', 'ra': 'base',  'rb':  ___,    'rcd': 'lit',   'mm': ___},

    {'name': 'LOOP',   'ra': 'rbase', 'rb':  ___,    'rcd': 'jump',  'mm': ___},
    {'name': 'ILOOP',  'ra': 'rbase', 'rb':  ___,    'rcd': 'jump',  'mm': ___},
    {'name': 'JLOOP',  'ra': 'rbase', 'rb':  ___,    'rcd': 'lit',   'mm': ___},

    {'name': 'JMP',    'ra': 'rbase', 'rb':  ___,    'rcd': 'jump',  'mm': ___},

    # Function headers. I/J = interp/JIT, F/V/C = fixarg/vararg/C func.
    {'name': 'FUNCF',  'ra': 'rbase', 'rb':  ___,    'rcd': ___,     'mm': ___},
    {'name': 'IFUNCF', 'ra': 'rbase', 'rb':  ___,    'rcd': ___,     'mm': ___},
    {'name': 'JFUNCF', 'ra': 'rbase', 'rb':  ___,    'rcd': 'lit',   'mm': ___},
    {'name': 'FUNCV',  'ra': 'rbase', 'rb':  ___,    'rcd': ___,     'mm': ___},
    {'name': 'IFUNCV', 'ra': 'rbase', 'rb':  ___,    'rcd': ___,     'mm': ___},
    {'name': 'JFUNCV', 'ra': 'rbase', 'rb':  ___,    'rcd': 'lit',   'mm': ___},
    {'name': 'FUNCC',  'ra': 'rbase', 'rb':  ___,    'rcd': ___,     'mm': ___},
    {'name': 'FUNCCW', 'ra': 'rbase', 'rb':  ___,    'rcd': ___,     'mm': ___},
]

def proto_bc(proto):
    return cast('BCIns *', cast('char *', proto) + gdb.lookup_type('GCproto').sizeof)

def proto_kgc(pt, idx):
    return gcref(mref('GCRef *', pt['k'])[idx])

def proto_knumtv(pt, idx):
    return mref('TValue *', pt['k'])[idx]

def frame_ftsz(framelink):
    return cast('ptrdiff_t', framelink['ftsz'] if LJ_FR2 \
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
    return cast('TValue *', cast('char *', framelink) - frame_sized(framelink))

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

# }}}

# Const {{{

LJ_64 = None
LJ_GC64 = None
LJ_FR2 = None
LJ_DUALNUM = None

LJ_GCVMASK = ((1 << 47) - 1)
LJ_TISNUM = None
PADDING = None

# These constants are meaningful only for 'LJ_64' mode.
LJ_LIGHTUD_BITS_SEG = 8
LJ_LIGHTUD_BITS_LO = 47 - LJ_LIGHTUD_BITS_SEG
LIGHTUD_SEG_MASK = (1 << LJ_LIGHTUD_BITS_SEG) - 1
LIGHTUD_LO_MASK = (1 << LJ_LIGHTUD_BITS_LO) - 1

# }}}

def itype(o):
    return cast('uint32_t', o['it64'] >> 47) if LJ_GC64 else o['it']

def mref(typename, obj):
    return cast(typename, obj['ptr64'] if LJ_GC64 else obj['ptr32'])

def gcref(obj):
    return cast('GCobj *', obj['gcptr64'] if LJ_GC64
        else cast('uintptr_t', obj['gcptr32']))

def gcval(obj):
    return cast('GCobj *', obj['gcptr64'] & LJ_GCVMASK if LJ_GC64
        else cast('uintptr_t', obj['gcptr32']))

def gcnext(obj):
    return gcref(obj)['gch']['nextgc']

def L(L=None):
    # lookup a symbol for the main coroutine considering the host app
    # XXX Fragile: though the loop initialization looks like a crap but it
    # respects both Python 2 and Python 3.
    for l in [ L ] + list(map(lambda l: lookup(l), (
        # LuaJIT main coro (see luajit/src/luajit.c)
        'globalL',
        # Tarantool main coro (see tarantool/src/lua/init.h)
        'tarantool_L',
        # TODO: Add more
    ))):
        if l:
            return cast('lua_State *', l)

def G(L):
    return mref('global_State *', L['glref'])

def J(g):
    typeGG = gtype('GG_State')

    return cast('jit_State *', int(cast('char *', g))
        - int(typeGG['g'].bitpos / 8)
        + int(typeGG['J'].bitpos / 8)
    )

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

def tvisint(o):
    return LJ_DUALNUM and itype(o) == LJ_TISNUM

def tvisnumber(o):
    return itype(o) <= LJ_TISNUM

def tvislightud(o):
    if LJ_64 and not LJ_GC64:
        return (cast('int32_t', itype(o)) >> 15) == -2
    else:
        return itype(o) == LJ_T['LIGHTUD']

def strdata(obj):
    # String is printed with pointer to it, thanks to gdb. Just strip it.
    try:
        return str(cast('char *', cast('GCstr *', obj) + 1))[len(PADDING):]
    except UnicodeEncodeError:
        return "<luajit-gdb: error occured while rendering non-ascii slot>"

def itypemap(o):
    if LJ_64 and not LJ_GC64:
        return LJ_T['NUMX'] if tvisnumber(o)       \
            else LJ_T['LIGHTUD'] if tvislightud(o) \
            else itype(o)
    else:
        return LJ_T['NUMX'] if tvisnumber(o) else itype(o)

def funcproto(func):
    assert(func['ffid'] == 0)

    return cast('GCproto *',
        mref('char *', func['pc']) - gdb.lookup_type('GCproto').sizeof)

def gclistlen(root, end=0x0):
    count = 0
    while(gcref(root) != end):
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

# Dumpers {{{

# GCobj dumpers.

def dump_lj_gco_str(gcobj):
    return 'string {body} @ {address}'.format(
        body = strdata(gcobj),
        address = strx64(gcobj)
    )

def dump_lj_gco_upval(gcobj):
    return 'upvalue @ {}'.format(strx64(gcobj))

def dump_lj_gco_thread(gcobj):
    return 'thread @ {}'.format(strx64(gcobj))

def dump_lj_gco_proto(gcobj):
    return 'proto @ {}'.format(strx64(gcobj))

def dump_lj_gco_func(gcobj):
    func = cast('struct GCfuncC *', gcobj)
    ffid = func['ffid']

    if ffid == 0:
        pt = funcproto(func)
        return 'Lua function @ {addr}, {nupvals} upvalues, {chunk}:{line}'.format(
            addr = strx64(func),
            nupvals = int(func['nupvalues']),
            chunk = strdata(cast('GCstr *', gcval(pt['chunkname']))),
            line = pt['firstline']
        )
    elif ffid == 1:
        return 'C function @ {}'.format(strx64(func['f']))
    else:
        return 'fast function #{}'.format(int(ffid))

def dump_lj_gco_trace(gcobj):
    trace = cast('struct GCtrace *', gcobj)
    return 'trace {traceno} @ {addr}'.format(
        traceno = strx64(trace['traceno']),
        addr = strx64(trace)
    )

def dump_lj_gco_cdata(gcobj):
    return 'cdata @ {}'.format(strx64(gcobj))

def dump_lj_gco_tab(gcobj):
    table = cast('GCtab *', gcobj)
    return 'table @ {gcr} (asize: {asize}, hmask: {hmask})'.format(
        gcr = strx64(table),
        asize = table['asize'],
        hmask = strx64(table['hmask']),
    )

def dump_lj_gco_udata(gcobj):
    return 'userdata @ {}'.format(strx64(gcobj))

def dump_lj_gco_invalid(gcobj):
    return 'not valid type @ {}'.format(strx64(gcobj))

# TValue dumpers.

def dump_lj_tv_nil(tv):
    return 'nil'

def dump_lj_tv_false(tv):
    return 'false'

def dump_lj_tv_true(tv):
    return 'true'

def dump_lj_tv_lightud(tv):
    return 'light userdata @ {}'.format(strx64(lightudV(tv)))

# Generate wrappers for TValues containing GCobj.
gco_fn_dumpers = [fn for fn in globals().keys() if fn.startswith('dump_lj_gco')]
for fn_name in gco_fn_dumpers:
    wrapped_fn_name = fn_name.replace('gco', 'tv')
    # lambda takes `fn_name` as reference, so need the additional
    # lambda to fixate the correct wrapper.
    globals()[wrapped_fn_name] = (lambda f: (
        lambda tv: globals()[f](gcval(tv['gcr']))
    ))(fn_name)

def dump_lj_tv_numx(tv):
    if tvisint(tv):
        return 'integer {}'.format(cast('int32_t', tv['i']))
    else:
        return 'number {}'.format(cast('double', tv['n']))

# }}}

gco_dumpers = {
    'LJ_TSTR':     dump_lj_gco_str,
    'LJ_TUPVAL':   dump_lj_gco_upval,
    'LJ_TTHREAD':  dump_lj_gco_thread,
    'LJ_TPROTO':   dump_lj_gco_proto,
    'LJ_TFUNC':    dump_lj_gco_func,
    'LJ_TTRACE':   dump_lj_gco_trace,
    'LJ_TCDATA':   dump_lj_gco_cdata,
    'LJ_TTAB':     dump_lj_gco_tab,
    'LJ_TUDATA':   dump_lj_gco_udata,
}

tv_dumpers = {
    'LJ_TNIL':     dump_lj_tv_nil,
    'LJ_TFALSE':   dump_lj_tv_false,
    'LJ_TTRUE':    dump_lj_tv_true,
    'LJ_TLIGHTUD': dump_lj_tv_lightud,
    'LJ_TSTR':     dump_lj_tv_str,
    'LJ_TUPVAL':   dump_lj_tv_upval,
    'LJ_TTHREAD':  dump_lj_tv_thread,
    'LJ_TPROTO':   dump_lj_tv_proto,
    'LJ_TFUNC':    dump_lj_tv_func,
    'LJ_TTRACE':   dump_lj_tv_trace,
    'LJ_TCDATA':   dump_lj_tv_cdata,
    'LJ_TTAB':     dump_lj_tv_tab,
    'LJ_TUDATA':   dump_lj_tv_udata,
    'LJ_TNUMX':    dump_lj_tv_numx,
}

def dump_gcobj(gcobj):
    return gco_dumpers.get(typenames(i2notu32(gcobj['gch']['gct'])), dump_lj_gco_invalid)(gcobj)

def dump_tvalue(tvalue):
    return tv_dumpers.get(typenames(itypemap(tvalue)), dump_lj_tv_invalid)(tvalue)

def dump_framelink_slot_address(fr):
    return '{}:{}'.format(fr - 1, fr) if LJ_FR2 \
        else '{}'.format(fr) + PADDING

def dump_framelink(L, fr):
    if fr == frame_sentinel(L):
        return '{addr} [S   ] FRAME: dummy L'.format(
            addr = dump_framelink_slot_address(fr),
        )
    return '{addr} [    ] FRAME: [{pp}] delta={d}, {f}'.format(
        addr = dump_framelink_slot_address(fr),
        pp = 'PP' if frame_ispcall(fr) else '{frname}{p}'.format(
            frname = frametypes(int(frame_type(fr))),
            p = 'P' if frame_typep(fr) & FRAME_P else ''
        ),
        d = cast('TValue *', fr) - cast('TValue *', frame_prev(fr)),
        f = dump_lj_tv_func(fr - LJ_FR2),
    )

def dump_stack_slot(L, slot, base=None, top=None):
    base = base or L['base']
    top = top or L['top']

    return '{addr}{padding} [ {B}{T}{M}] VALUE: {value}'.format(
        addr = strx64(slot),
        padding = PADDING,
        B = 'B' if slot == base else ' ',
        T = 'T' if slot == top else ' ',
        M = 'M' if slot == mref('TValue *', L['maxstack']) else ' ',
        value = dump_tvalue(slot),
    )

def dump_stack(L, base=None, top=None):
    base = base or L['base']
    top = top or L['top']
    stack = mref('TValue *', L['stack'])
    maxstack = mref('TValue *', L['maxstack'])
    red = 5 + 2 * LJ_FR2

    dump = [
        '{padding} Red zone: {nredslots: >2} slots {padding}'.format(
            padding = '-' * len(PADDING),
            nredslots = red,
        ),
    ]
    dump.extend([
        dump_stack_slot(L, maxstack + offset, base, top)
            for offset in range(red, 0, -1)
    ])
    dump.extend([
        '{padding} Stack: {nstackslots: >5} slots {padding}'.format(
            padding = '-' * len(PADDING),
            nstackslots = int((tou64(maxstack) - tou64(stack)) >> 3),
        ),
        dump_stack_slot(L, maxstack, base, top),
        '{start}:{end} [    ] {nfreeslots} slots: Free stack slots'.format(
            start = strx64(top + 1),
            end = strx64(maxstack - 1),
            nfreeslots = int((tou64(maxstack) - tou64(top) - 8) >> 3),
        ),
    ])

    for framelink, frametop in frames(L):
        # Dump all data slots in the (framelink, top) interval.
        dump.extend([
            dump_stack_slot(L, framelink + offset, base, top)
                for offset in range(frametop - framelink, 0, -1)
        ])
        # Dump frame slot (2 slots in case of GC64).
        dump.append(dump_framelink(L, framelink))

    return '\n'.join(dump)

def dump_gc(g):
    gc = g['gc']
    stats = [ '{key}: {value}'.format(key = f, value = gc[f]) for f in (
        'total', 'threshold', 'debt', 'estimate', 'stepmul', 'pause'
    ) ]

    stats += [ 'sweepstr: {sweepstr}/{strmask}'.format(
        sweepstr = gc['sweepstr'],
        # String hash mask (size of hash table - 1).
        strmask = g['strmask'] + 1,
    ) ]

    stats += [ '{key}: {number} objects'.format(
        key = stat,
        number = handler(gc[stat])
    ) for stat, handler in gclen.items() ]

    return '\n'.join(map(lambda s: '\t' + s, stats))

def proto_loc(proto):
    return '{chunk}:{firstline}'.format(
        chunk = strdata(cast('GCstr *', gcval(proto['chunkname']))),
        firstline = proto['firstline'],
    )

def funck(pt, idx):
    if idx >= 0:
        assert idx < pt['sizekn'], 'invalid idx for numeric constant in proto'
        tv = proto_knumtv(pt, idx)
        return dump_tvalue(tv)
    else:
        assert ~idx < pt['sizekgc'], 'invalid idx for GC constant in proto'
        gcobj = proto_kgc(pt, idx)
        if typenames(i2notu32(gcobj['gch']['gct'])) == 'LJ_TPROTO':
            return proto_loc(cast('GCproto *', gcobj))
        return dump_gcobj(gcobj)

def funcuvname(pt, idx):
    assert idx < pt['sizeuv'], 'invalid idx for upvalue in proto'
    uvinfo = mref('uint8_t *', pt['uvinfo'])
    if not uvinfo:
        return ''

    # if (idx) while (*uvinfo++ || --idx);
    while idx > 0:
        while uvinfo[0]:
            uvinfo += 1
        uvinfo += 1
        idx -= 1

    return str(cast('char *', uvinfo))

def dump_reg(rtype, value, jmp_format=None, jmp_ctx=None):
    is_jmp = rtype == 'jump'

    if rtype == 'jump':
        # Destination of jump instruction encoded as offset from BCBIAS_J.
        delta = value - 0x7fff
        if jmp_format:
            value = jmp_format(jmp_ctx, delta)
        else:
            prefix = '+' if delta >= 0 else ''
            value = prefix + str(delta)
    else:
        value = '{:3d}'.format(value)

    return '{rtype:6} {value}'.format(
        rtype = rtype + ':',
        value = value,
    )

def dump_kc(rtype, value, proto, bcname):
    kc = ''
    if proto:
        if rtype == 'str' or rtype == 'func':
            kc = funck(proto, ~value)
        elif rtype == 'num':
            kc = funck(proto, value)
        elif rtype == 'uv':
            kc = funcuvname(proto, value)

        if kc != '':
            if bcname == 'TSETM':
                match = re.match(r'number (\d+)', kc)
                assert match, 'Unexpected TSETM constant ref'
                kc = 'number {}'.format(int(match.group(1)) - 2 ** 52)
            kc = ' ; ' + kc
    return kc

def dump_bc(ins, jmp_format=None, jmp_ctx=None, proto=None):
    op = bc_op(ins)
    if op >= len(BYTECODES):
        return 'INVALID'

    bc = BYTECODES[op]
    name = bc['name']

    kca = dump_kc(bc['ra'], bc_a(ins), proto, name) if bc['ra'] else ''
    kcc = dump_kc(
        bc['rcd'], bc_c(ins) if bc['rb'] else bc_d(ins), proto, name
    ) if bc['rcd'] else ''

    return '{name:6} {ra}{rb}{rcd}{kc}'.format(
        name = name,
        ra = dump_reg(bc['ra'], bc_a(ins)) + ' ' if bc['ra'] else '',
        rb = dump_reg(bc['rb'], bc_b(ins)) + ' ' if bc['rb'] else '',
        rcd = dump_reg(
            bc['rcd'], bc_c(ins) if bc['rb'] else bc_d(ins),
            jmp_format=jmp_format, jmp_ctx=jmp_ctx
        ) if bc['rcd'] else '',
        kc = kca + kcc
    )

def dump_proto(proto):
    startbc = proto_bc(proto)
    func_loc = proto_loc(proto)
    # Location has the following format: '{chunk}:{firstline}'.
    dump = '{func_loc}-{lastline}\n'.format(
        func_loc = func_loc,
        lastline = proto['firstline'] + proto['numline'],
    )

    def jmp_format(npc_from, delta):
        return '=> ' + str(npc_from + delta).zfill(4)

    for bcnum in range(0, proto['sizebc']):
        dump += (str(bcnum).zfill(4) + ' ' + dump_bc(
            startbc[bcnum], jmp_format=jmp_format, jmp_ctx=bcnum,
            proto = proto,
        ) + '\n')
    return dump

def dump_func(func):
    ffid = func['ffid']

    if ffid == 0:
        pt = funcproto(func)
        return dump_proto(pt)
    elif ffid == 1:
        return 'C function @ {}\n'.format(strx64(func['f']))
    else:
        return 'fast function #{}\n'.format(int(ffid))

class LJBase(gdb.Command):

    def __init__(self, name):
        # XXX Fragile: though the command initialization looks like a crap but
        # it respects both Python 2 and Python 3.
        gdb.Command.__init__(self, name, gdb.COMMAND_DATA)
        gdb.write('{} command initialized\n'.format(name))

class LJDumpArch(LJBase):
    '''
lj-arch

The command requires no args and dumps values of LJ_64 and LJ_GC64
compile-time flags. These values define the sizes of host and GC
pointers respectively.
    '''

    def invoke(self, arg, from_tty):
        gdb.write(
            'LJ_64: {LJ_64}, LJ_GC64: {LJ_GC64}, LJ_DUALNUM: {LJ_DUALNUM}\n'
            .format(
                LJ_64 = LJ_64,
                LJ_GC64 = LJ_GC64,
                LJ_DUALNUM = LJ_DUALNUM
            )
        )

class LJDumpTValue(LJBase):
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

    def invoke(self, arg, from_tty):
        tv = cast('TValue *', parse_arg(arg))
        gdb.write('{}\n'.format(dump_tvalue(tv)))

class LJDumpString(LJBase):
    '''
lj-str <GCstr *>

The command receives a <gcr> of the corresponding GCstr object and dumps
the payload, size in bytes and hash.

*Caveat*: Since Python 2 provides no native Unicode support, the payload
is replaced with the corresponding error when decoding fails.
    '''

    def invoke(self, arg, from_tty):
        string = cast('GCstr *', parse_arg(arg))
        gdb.write("String: {body} [{len} bytes] with hash {hash}\n".format(
            body = strdata(string),
            hash = strx64(string['hash']),
            len = string['len'],
        ))

class LJDumpTable(LJBase):
    '''
lj-tab <GCtab *>

The command receives a GCtab adress and dumps the table contents:
* Metatable address whether the one is set
* Array part <asize> slots:
  <aslot ptr>: [<index>]: <tv>
* Hash part <hsize> nodes:
  <hnode ptr>: { <tv> } => { <tv> }; next = <next hnode ptr>
    '''

    def invoke(self, arg, from_tty):
        t = cast('GCtab *', parse_arg(arg))
        array = mref('TValue *', t['array'])
        nodes = mref('struct Node *', t['node'])
        mt = gcval(t['metatable'])
        capacity = {
            'apart': int(t['asize']),
            'hpart': int(t['hmask'] + 1) if t['hmask'] > 0 else 0
        }

        if mt != 0:
            gdb.write('Metatable detected: {}\n'.format(strx64(mt)))

        gdb.write('Array part: {} slots\n'.format(capacity['apart']))
        for i in range(capacity['apart']):
            slot = array + i
            gdb.write('{ptr}: [{index}]: {value}\n'.format(
                ptr = slot,
                index = i,
                value = dump_tvalue(slot)
            ))

        gdb.write('Hash part: {} nodes\n'.format(capacity['hpart']))
        # See hmask comment in lj_obj.h
        for i in range(capacity['hpart']):
            node = nodes + i
            gdb.write('{ptr}: {{ {key} }} => {{ {val} }}; next = {n}\n'.format(
                ptr = node,
                key = dump_tvalue(node['key']),
                val= dump_tvalue(node['val']),
                n = mref('struct Node *', node['next'])
            ))

class LJDumpStack(LJBase):
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

If L is ommited the main coroutine is used.
    '''

    def invoke(self, arg, from_tty):
        gdb.write('{}\n'.format(dump_stack(L(parse_arg(arg)))))

class LJState(LJBase):
    '''
lj-state
The command requires no args and dumps current VM and GC states
* VM state: <INTERP|C|GC|EXIT|RECORD|OPT|ASM|TRACE>
* GC state: <PAUSE|PROPAGATE|ATOMIC|SWEEPSTRING|SWEEP|FINALIZE|LAST>
* JIT state: <IDLE|ACTIVE|RECORD|START|END|ASM|ERR>
    '''

    def invoke(self, arg, from_tty):
        g = G(L(None))
        gdb.write('{}\n'.format('\n'.join(
            map(lambda t: '{} state: {}'.format(*t), {
                'VM': vm_state(g),
                'GC': gc_state(g),
                'JIT': jit_state(g),
            }.items())
        )))

class LJGC(LJBase):
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

    def invoke(self, arg, from_tty):
        g = G(L(None))
        gdb.write('GC stats: {state}\n{stats}\n'.format(
            state = gc_state(g),
            stats = dump_gc(g)
        ))

class LJDumpBC(LJBase):
    '''
lj-bc <BCIns *>

The command receives a pointer to bytecode instruction and dumps
type of an instruction, the values of RA, RB and RC (or RD) registers.
    '''

    def invoke(self, arg, from_tty):
        gdb.write('{}\n'.format(dump_bc(cast("BCIns *", parse_arg(arg))[0])))

class LJDumpProto(LJBase):
    '''
lj-proto <GCproto *>

The command receives a <gcr> of the corresponding GCproto object and dumps
the chunk name, where the corresponding function is defined, corresponding
range of lines and a list of bytecodes related to this function.

The constants or upvalues of the prototype are decoded after ';'.
    '''

    def invoke(self, arg, from_tty):
        gdb.write('{}'.format(dump_proto(cast("GCproto *", parse_arg(arg)))))

class LJDumpFunc(LJBase):
    '''
lj-func <GCfunc *>

The command receives a <gcr> of the corresponding GCfunc object and dumps
the chunk name, where the corresponding function is defined, corresponding
range of lines and a list of bytecodes related to this function.

The constants or upvalues of the function are decoded after ';'.
    '''

    def invoke(self, arg, from_tty):
        gdb.write('{}'.format(dump_func(cast("GCfuncC *", parse_arg(arg)))))

def init(commands):
    global LJ_64, LJ_GC64, LJ_FR2, LJ_DUALNUM, LJ_TISNUM, PADDING

    # XXX Fragile: though connecting the callback looks like a crap but it
    # respects both Python 2 and Python 3 (see #4828).
    def connect(callback):
        if LEGACY:
            global CONNECTED
            CONNECTED = True
        gdb.events.new_objfile.connect(callback)

    # XXX Fragile: though disconnecting the callback looks like a crap but it
    # respects both Python 2 and Python 3 (see #4828).
    def disconnect(callback):
        if LEGACY:
            global CONNECTED
            if not CONNECTED:
                return
            CONNECTED = False
        gdb.events.new_objfile.disconnect(callback)

    try:
        # Try to remove the callback at first to not append duplicates to
        # gdb.events.new_objfile internal list.
        disconnect(load)
    except:
        # Callback is not connected.
        pass

    try:
        # Detect whether libluajit objfile is loaded.
        gdb.parse_and_eval('luaJIT_setmode')
    except:
        gdb.write('luajit-gdb.py initialization is postponed '
                  'until libluajit objfile is loaded\n')
        # Add a callback to be executed when the next objfile is loaded.
        connect(load)
        return

    try:
        LJ_64 = str(gdb.parse_and_eval('IRT_PTR')) == 'IRT_P64'
        LJ_FR2 = LJ_GC64 = str(gdb.parse_and_eval('IRT_PGC')) == 'IRT_P64'
        LJ_DUALNUM = gdb.lookup_global_symbol('lj_lib_checknumber') is not None
    except:
        gdb.write('luajit-gdb.py failed to load: '
                  'no debugging symbols found for libluajit\n')
        return

    for name, command in commands.items():
        command(name)

    PADDING = ' ' * len(':' + hex((1 << (47 if LJ_GC64 else 32)) - 1))
    LJ_TISNUM = 0xfffeffff if LJ_64 and not LJ_GC64 else LJ_T['NUMX']

    gdb.write('luajit-gdb.py is successfully loaded\n')

def load(event=None):
    init({
        'lj-arch': LJDumpArch,
        'lj-tv': LJDumpTValue,
        'lj-str': LJDumpString,
        'lj-tab': LJDumpTable,
        'lj-stack': LJDumpStack,
        'lj-state': LJState,
        'lj-gc': LJGC,
        'lj-bc': LJDumpBC,
        'lj-proto': LJDumpProto,
        'lj-func': LJDumpFunc,
    })

load(None)
