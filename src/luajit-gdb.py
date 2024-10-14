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

def parse_flags(raw_flags, permitted_flags):
    flags = {}
    for flag in raw_flags:
        if not flag in permitted_flags:
            raise gdb.GdbError('Unrecongnized option: "{}"'.format(flag))
        flags[flag] = True

    return flags

def extract_flags(arg, permitted_flags):
    if not arg:
        return None, None

    flags = {}
    if arg.startswith('/'):
        match = re.fullmatch(r'/(\S*)\s+(.*)', arg)
        if not match:
            return arg, flags
        raw_flags, arg = match.group(1, 2)
        flags = parse_flags(raw_flags, permitted_flags)

    return arg, flags

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

MM_NAMES = [
    'index',
    'newindex',
    'gc',
    'mode',
    'eq',
    'len',
    'lt',
    'le',
    'concat',
    'call',
    'add',
    'sub',
    'mul',
    'div',
    'mod',
    'pow',
    'unm',
    'metatable',
    'tostring',
    # TODO: depends on LJ_HASFFI, see MMDEF_FFI(_).
    'new',
    # TODO: depends on LJ_52 || LJ_HASFFI, see MMDEF_PAIRS(_).
    'pairs',
    'ipairs',
]

GCROOT_MMNAME = 0
GCROOT_BASEMT = GCROOT_MMNAME + len(MM_NAMES)
GCROOT_IO_INPUT = GCROOT_BASEMT + i2notu32(LJ_T['NUMX']) + 1
GCROOT_IO_OUTPUT = GCROOT_IO_INPUT + 1

def idx_name(field_name):
    return {
        'ksimd': {
            0 * 2: 'LJ_KSIMD_ABS',
            1 * 2: 'LJ_KSIMD_NEG',
        },
        # TODO: gcroot.
        'gcroot': {
            **{
                i: 'GCROOT_MMNAME_' + MM_NAMES[i] for i in range(len(MM_NAMES))
            }, **{
                i2notu32(LJ_T[k]) + GCROOT_BASEMT: \
                    'GCROOT_BASEMT_' + k for k in LJ_T.keys()
            }, **{
                GCROOT_IO_INPUT:  'GCROOT_IO_INPUT',
                GCROOT_IO_OUTPUT: 'GCROOT_IO_OUTPUT',
            }
        }
    }.get(field_name, None)


def type_ofs_path(tp, offset, prev_name=None):
    assert offset < tp.sizeof, 'offset is bigger than object size'
    if tp.code == gdb.TYPE_CODE_TYPEDEF:
        tp = tp.strip_typedefs()
    if tp.code == gdb.TYPE_CODE_STRUCT:
        fields = tp.fields()
        for n_field in range(len(fields)):
            islast = n_field == (len(fields) - 1)
            field = fields[n_field]
            start_field = field.bitpos / 8
            end_field = fields[n_field + 1].bitpos / 8 if not islast else tp.sizeof
            if start_field <= offset and offset < end_field:
                next_name = type_ofs_path(field.type, offset - start_field, field.name)
                return '.{}{}'.format(field.name, next_name if next_name else '')
    elif tp.code == gdb.TYPE_CODE_ARRAY:
        # Get array field type.
        target = tp.target()
        tsize = target.sizeof
        idx = int(offset // tsize)
        next_name = type_ofs_path(target, offset - idx * tsize)

        idxname = idx_name(prev_name)
        if idxname and idx in idxname:
            idx = idxname[idx]
        return '[{}]{}'.format(idx, next_name if next_name else '')
    else:
        return None

ggfname_cache = {}
def ggfname_by_offset(offset):
    if offset in ggfname_cache:
        return ggfname_cache[offset]

    field_path = type_ofs_path(gtype('GG_State'), offset)
    if not field_path:
        return None

    # Remove first '.'.
    ggfname = 'offsetof(GG, {})'.format(field_path[1:])
    ggfname_cache[offset] = ggfname
    return ggfname

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

# TODO: determine mode from lj_ir_mode[op].
# Maybe left, right too?
IRS = [
    # Guarded assertions.
    {'name': 'LT',     'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'GE',     'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'LE',     'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'GT',     'mode': 'N',  'left': 'ref', 'right': 'ref'},

    {'name': 'ULT',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'UGE',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'ULE',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'UGT',    'mode': 'N',  'left': 'ref', 'right': 'ref'},

    {'name': 'EQ',     'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'NE',     'mode': 'C',  'left': 'ref', 'right': 'ref'},

    {'name': 'ABC',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'RETF',   'mode': 'S',  'left': 'ref', 'right': 'ref'},

    # Miscellaneous ops.
    {'name': 'NOP',    'mode': 'N',  'left': ___,   'right': ___},
    {'name': 'BASE',   'mode': 'N',  'left': 'lit', 'right': 'lit'},
    {'name': 'PVAL',   'mode': 'N',  'left': 'lit', 'right': ___},
    {'name': 'GCSTEP', 'mode': 'S',  'left': ___,   'right': ___},
    {'name': 'HIOP',   'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'LOOP',   'mode': 'S',  'left': ___,   'right': ___},
    {'name': 'USE',    'mode': 'S',  'left': 'ref', 'right': ___},
    {'name': 'PHI',    'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'RENAME', 'mode': 'S',  'left': 'ref', 'right': 'lit'},
    {'name': 'PROF',   'mode': 'S',  'left': ___,   'right': ___},

    # Constants.
    {'name': 'KPRI',   'mode': 'N',  'left': ___,   'right': ___},
    {'name': 'KINT',   'mode': 'N',  'left': 'cst', 'right': ___},
    {'name': 'KGC',    'mode': 'N',  'left': 'cst', 'right': ___},
    {'name': 'KPTR',   'mode': 'N',  'left': 'cst', 'right': ___},
    {'name': 'KKPTR',  'mode': 'N',  'left': 'cst', 'right': ___},
    {'name': 'KNULL',  'mode': 'N',  'left': 'cst', 'right': ___},
    {'name': 'KNUM',   'mode': 'N',  'left': 'cst', 'right': ___},
    {'name': 'KINT64', 'mode': 'N',  'left': 'cst', 'right': ___},
    {'name': 'KSLOT',  'mode': 'N',  'left': 'ref', 'right': 'lit'},

    # Bit ops.
    {'name': 'BNOT',   'mode': 'N',  'left': 'ref', 'right': ___},
    {'name': 'BSWAP',  'mode': 'N',  'left': 'ref', 'right': ___},
    {'name': 'BAND',   'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'BOR',    'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'BXOR',   'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'BSHL',   'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'BSHR',   'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'BSAR',   'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'BROL',   'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'BROR',   'mode': 'N',  'left': 'ref', 'right': 'ref'},

    # Arithmetic ops. ORDER ARITH
    {'name': 'ADD',    'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'SUB',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'MUL',    'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'DIV',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'MOD',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'POW',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'NEG',    'mode': 'N',  'left': 'ref', 'right': 'ref'},

    {'name': 'ABS',    'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'LDEXP',  'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'MIN',    'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'MAX',    'mode': 'C',  'left': 'ref', 'right': 'ref'},
    {'name': 'FPMATH', 'mode': 'N',  'left': 'ref', 'right': 'lit'},

    # Overflow-checking arithmetic ops.
    {'name': 'ADDOV',  'mode': 'CW', 'left': 'ref', 'right': 'ref'},
    {'name': 'SUBOV',  'mode': 'NW', 'left': 'ref', 'right': 'ref'},
    {'name': 'MULOV',  'mode': 'CW', 'left': 'ref', 'right': 'ref'},

    # Memory ops. A = array, H = hash, U = upvalue, F = field, S = stack.

    # Memory references.
    {'name': 'AREF',   'mode': 'R',  'left': 'ref', 'right': 'ref'},
    {'name': 'HREFK',  'mode': 'R',  'left': 'ref', 'right': 'ref'},
    {'name': 'HREF',   'mode': 'L',  'left': 'ref', 'right': 'ref'},
    {'name': 'NEWREF', 'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'UREFO',  'mode': 'LW', 'left': 'ref', 'right': 'lit'},
    {'name': 'UREFC',  'mode': 'LW', 'left': 'ref', 'right': 'lit'},
    {'name': 'FREF',   'mode': 'R',  'left': 'ref', 'right': 'lit'},
    {'name': 'STRREF', 'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'LREF',   'mode': 'L',  'left': ___,   'right': ___},

    # Loads and Stores. These must be in the same order.
    {'name': 'ALOAD',  'mode': 'L',  'left': 'ref', 'right': ___},
    {'name': 'HLOAD',  'mode': 'L',  'left': 'ref', 'right': ___},
    {'name': 'ULOAD',  'mode': 'L',  'left': 'ref', 'right': ___},
    {'name': 'FLOAD',  'mode': 'L',  'left': 'ref', 'right': 'lit'},
    {'name': 'XLOAD',  'mode': 'L',  'left': 'ref', 'right': 'lit'},
    {'name': 'SLOAD',  'mode': 'L',  'left': 'lit', 'right': 'lit'},
    {'name': 'VLOAD',  'mode': 'L',  'left': 'ref', 'right': ___},

    {'name': 'ASTORE', 'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'HSTORE', 'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'USTORE', 'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'FSTORE', 'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'XSTORE', 'mode': 'S',  'left': 'ref', 'right': 'ref'},

    # Allocations.
    {'name': 'SNEW',   'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'XSNEW',  'mode': 'A',  'left': 'ref', 'right': 'ref'},
    {'name': 'TNEW',   'mode': 'AW', 'left': 'lit', 'right': 'lit'},
    {'name': 'TDUP',   'mode': 'AW', 'left': 'ref', 'right': ___},
    {'name': 'CNEW',   'mode': 'AW', 'left': 'ref', 'right': 'ref'},
    {'name': 'CNEWI',  'mode': 'NW', 'left': 'ref', 'right': 'ref'},

    # Buffer operations.
    {'name': 'BUFHDR', 'mode': 'L',  'left': 'ref', 'right': 'lit'},
    {'name': 'BUFPUT', 'mode': 'L',  'left': 'ref', 'right': 'ref'},
    {'name': 'BUFSTR', 'mode': 'A',  'left': 'ref', 'right': 'ref'},

    # Barriers.
    {'name': 'TBAR',   'mode': 'S',  'left': 'ref', 'right': ___},
    {'name': 'OBAR',   'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'XBAR',   'mode': 'S',  'left': ___,   'right': ___},

    # Type conversions.
    {'name': 'CONV',   'mode': 'N',  'left': 'ref', 'right': 'lit'},
    {'name': 'TOBIT',  'mode': 'N',  'left': 'ref', 'right': 'ref'},
    {'name': 'TOSTR',  'mode': 'N',  'left': 'ref', 'right': 'lit'},
    {'name': 'STRTO',  'mode': 'N',  'left': 'ref', 'right': ___},

    # Calls.
    {'name': 'CALLN',  'mode': 'N',  'left': 'ref', 'right': 'lit'},
    {'name': 'CALLA',  'mode': 'A',  'left': 'ref', 'right': 'lit'},
    {'name': 'CALLL',  'mode': 'L',  'left': 'ref', 'right': 'lit'},
    {'name': 'CALLS',  'mode': 'S',  'left': 'ref', 'right': 'lit'},
    {'name': 'CALLXS', 'mode': 'S',  'left': 'ref', 'right': 'ref'},
    {'name': 'CARG',   'mode': 'N',  'left': 'ref', 'right': 'ref'},
]

IRTYPES = [
  'nil',
  'fal',
  'tru',
  'lud',
  'str',
  'p32',
  'thr',
  'pro',
  'fun',
  'p64',
  'cdt',
  'tab',
  'udt',
  'flt',
  'num',
  'i8 ',
  'u8 ',
  'i16',
  'u16',
  'int',
  'u32',
  'i64',
  'u64',
  'sfp',
]

# FIXME: merge with short.
# IR types.
IRT = {
    'NIL':     1,
    'FALSE':   2,
    'TRUE':    3,
    'LIGHTUD': 4,
    'STR':     5,
    'P32':     6,
    'THREAD':  7,
    'PROTO':   8,
    'FUNC':    9,
    'P64':     10,
    'CDATA':   11,
    'TAB':     12,
    'UDATA':   13,
    'FLOAT':   14,
    'NUM':     15,
    'I8':      16,
    'U8':      17,
    'I16':     18,
    'U16':     19,
    'INT':     20,
    'U32':     21,
    'I64':     22,
    'U64':     23,
    'SOFTFP':  24,
}

IRFIELDS = [
    'str.len',
    'func.env',
    'func.pc',
    'func.ffid',
    'thread.env',
    'tab.meta',
    'tab.array',
    'tab.node',
    'tab.asize',
    'tab.hmask',
    'tab.nomm',
    'udata.meta',
    'udata.udtype',
    'udata.file',
    'cdata.ctypeid',
    'cdata.ptr',
    'cdata.int',
    'cdata.int64',
    'cdata.int64_4',
]

IRFPMS = [
    'floor',
    'ceil',
    'trunc',
    'sqrt',
    'exp2',
    'log',
    'log2',
    'other'
]

REGISTERS = {'x64': [
    'rax',
    'rcx',
    'rdx',
    'rbx',
    'rsp',
    'rbp',
    'rsi',
    'rdi',
    'r8',
    'r9',
    'r10',
    'r11',
    'r12',
    'r13',
    'r14',
    'r15',
    'xmm1',
    'xmm2',
    'xmm3',
    'xmm4',
    'xmm5',
    'xmm6',
    'xmm7',
    'xmm8',
    'xmm9',
    'xmm10',
    'xmm11',
    'xmm12',
    'xmm13',
    'xmm14',
    'xmm15',
    'xmm16',
]}

IR_CALLS = [
    'lj_str_cmp',
    'lj_str_find',
    'lj_str_new',
    'lj_strscan_num',
    'lj_strfmt_int',
    'lj_strfmt_num',
    'lj_strfmt_char',
    'lj_strfmt_putint',
    'lj_strfmt_putnum',
    'lj_strfmt_putquoted',
    'lj_strfmt_putfxint',
    'lj_strfmt_putfnum_int',
    'lj_strfmt_putfnum_uint',
    'lj_strfmt_putfnum',
    'lj_strfmt_putfstr',
    'lj_strfmt_putfchar',
    'lj_buf_putmem',
    'lj_buf_putstr',
    'lj_buf_putchar',
    'lj_buf_putstr_reverse',
    'lj_buf_putstr_lower',
    'lj_buf_putstr_upper',
    'lj_buf_putstr_rep',
    'lj_buf_puttab',
    'lj_buf_tostr',
    'lj_tab_new_ah',
    'lj_tab_new1',
    'lj_tab_dup',
    'lj_tab_clear',
    'lj_tab_newkey',
    'lj_tab_len',
    'lj_gc_step_jit',
    'lj_gc_barrieruv',
    'lj_mem_newgco',
    'lj_math_random_step',
    'lj_vm_modi',
    'log10',
    'exp',
    'sin',
    'cos',
    'tan',
    'asin',
    'acos',
    'atan',
    'sinh',
    'cosh',
    'tanh',
    'fputc',
    'fwrite',
    'fflush',
    'lj_vm_floor',
    'lj_vm_ceil',
    'lj_vm_trunc',
    'sqrt',
    'log',
    'lj_vm_log2',
    'pow',
    'atan2',
    'ldexp',
    'lj_vm_tobit',
    'softfp_add',
    'softfp_sub',
    'softfp_mul',
    'softfp_div',
    'softfp_cmp',
    'softfp_i2d',
    'softfp_d2i',
    'lj_vm_sfmin',
    'lj_vm_sfmax',
    'lj_vm_tointg',
    'softfp_ui2d',
    'softfp_f2d',
    'softfp_d2ui',
    'softfp_d2f',
    'softfp_i2f',
    'softfp_ui2f',
    'softfp_f2i',
    'softfp_f2ui',
    'fp64_l2d',
    'fp64_ul2d',
    'fp64_l2f',
    'fp64_ul2f',
    'fp64_d2l',
    'fp64_d2ul',
    'fp64_f2l',
    'fp64_f2ul',
    'lj_carith_divi64',
    'lj_carith_divu64',
    'lj_carith_modi64',
    'lj_carith_modu64',
    'lj_carith_powi64',
    'lj_carith_powu64',
    'lj_cdata_newv',
    'lj_cdata_setfin',
    'strlen',
    'memcpy',
    'memset',
    'lj_vm_errno',
    'lj_carith_mul64',
    'lj_carith_shl64',
    'lj_carith_shr64',
    'lj_carith_sar64',
    'lj_carith_rol64',
    'lj_carith_ror64',
]

def archname():
    try:
        arch = str(gdb.parse_and_eval('LJ_ARCH_NAME')).replace('"', '')
    except:
        target = str(gdb.execute('info target', False, True))
        if re.match('.*x86-64.*', target, flags=re.DOTALL):
            return 'x64'
        else:
            raise gdb.GdbError('Unknown target architecture')

    return arch

def regname(reg_number):
    arch = archname()
    return REGISTERS[arch][reg_number]

def litname_sload(mode):
    modes_str = ''
    modes_str += 'P' if mode & 0x1  else ''
    modes_str += 'F' if mode & 0x2  else ''
    modes_str += 'T' if mode & 0x4  else ''
    modes_str += 'C' if mode & 0x8  else ''
    modes_str += 'R' if mode & 0x10 else ''
    modes_str += 'I' if mode & 0x20 else ''
    return modes_str

def litname_xload(mode):
    flags = ['-', 'R', 'V', 'RV', 'U', 'RU', 'VU', 'RVU']
    return flags[mode]

def litname_conv(mode):
    IRCONV_DSH = 5
    IRCONV_CSH = 12
    IRCONV_SEXT = 0x800
    IRCONV_SRCMASK = 0x1f
    conv_str = '{to}.{frm}'.format(
        to = IRTYPES[(mode >> IRCONV_DSH) & IRCONV_SRCMASK],
        frm = IRTYPES[mode & IRCONV_SRCMASK]
    )
    conv_str += ' sext' if mode & IRCONV_SEXT else ''
    num2int_mode = mode >> IRCONV_CSH
    if num2int_mode == 2:
        conv_str += " index"
    elif num2int_mode == 3:
        conv_str += " check"
    return conv_str

def litname_irfield(mode):
    if mode >= len(IRFIELDS):
        return 'unknown irfield'
    return IRFIELDS[mode]

def litname_fpm(mode):
    if mode >= len(IRFPMS):
        return 'unknown irfpm'
    return IRFPMS[mode]

def litname_bufhdr(mode):
    modes = ['RESET', 'APPEND']
    if mode >= len(modes):
        return 'unknown bufhdr mode'
    return modes[mode]

def litname_tostr(mode):
    modes = ['INT', 'NUM', 'CHAR']
    if mode >= len(modes):
        return 'unknown tostr mode'
    return modes[mode]

IR_LITNAMES = {
    'SLOAD':  litname_sload,
    'XLOAD':  litname_xload,
    'CONV':   litname_conv,
    'FLOAD':  litname_irfield,
    'FREF':   litname_irfield,
    'FPMATH': litname_fpm,
    'BUFHDR': litname_bufhdr,
    'TOSTR':  litname_tostr
}

# Additional flags.
IRT_MARK  = 0x20 # Marker for misc. purposes.
IRT_ISPHI = 0x40 # Instruction is left or right PHI operand.
IRT_GUARD = 0x80 # Instruction is a guard.
# Masks.
IRT_TYPE = 0x1f

RID_NONE = 0x80
RID_MASK = 0x7f
RID_INIT = (RID_NONE | RID_MASK)
RID_SINK = (RID_INIT - 1)
RID_SUNK = (RID_INIT - 2)
# Spill slot 0 means no spill slot has been allocated.
SPS_NONE = 0

REF_BIAS = 0x8000

TREF_SHIFT = 24

TREF_REFMASK = 0x0000ffff
TREF_FRAME   = 0x00010000
TREF_CONT    = 0x00020000
# Snapshot flags and masks.
SNAP_FRAME     = 0x010000
SNAP_SOFTFPNUM = 0x080000

def irt_type(t):
    return cast('IRType', t['irt'] & IRT_TYPE)

def tref_type(tr):
    return cast('IRType', (tr >> TREF_SHIFT) & IRT_TYPE)

def tref_ref(tr):
    return int(tr & TREF_REFMASK)

def irt_ismarked(t):
    return t['irt'] & IRT_MARK

def irt_isphi(t):
    return t['irt'] & IRT_ISPHI

def irt_isguard(t):
    return t['irt'] & IRT_GUARD

def irt_toitype(irt):
    t = irt_type(irt)
    if t >= IRT['NUM']:
        return LJ_T['NUMX']
    else:
        return i2notu32(t)

def ir_kptr(ir):
    irname = IRS[ir['o']]['name']
    assert irname == 'KPTR' or irname == 'KKPTR', 'wrong IR for ir_iptr()'
    return mref('void *', cast('IRIns *', ir.address)[LJ_GC64]['ptr'])

def ir_kgc(ir):
    irname = IRS[ir['o']]['name']
    assert irname == 'KGC', 'wrong IR for ir_kgc()'
    return gcref(cast('IRIns *', ir.address)[LJ_GC64]['gcr'])

def ir_knum(ir):
    irname = IRS[ir['o']]['name']
    assert irname == 'KNUM', 'wrong IR for ir_knum()'
    return cast('IRIns *', ir.address)[1]['tv'].address

def ir_kint64(ir):
    irname = IRS[ir['o']]['name']
    assert irname == 'KINT64', 'wrong IR for ir_knum()'
    return cast('IRIns *', ir.address)[1]['tv'].address

def ctype_ctsG(g):
    return mref('CTState *', g['ctype_state'])

def ctype_get(cts, id):
    return cts['tab'][id].address

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
    # + 1 since Gdb bug, it64 is defined only on GC64, so check is needed
    add = ((cast('uint64_t', o['it64']) & (1 << 46)) >> 46) if LJ_GC64 else 0
    return cast('uint32_t', (o['it64'] >> 47) - add) if LJ_GC64 else o['it']

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

# Externally visible types.
CT_NUM = 0 # Integer or floating-point numbers.
CT_STRUCT = 1 # Struct or union.
CT_PTR = 2 # Pointer or reference.
CT_ARRAY = 3 # Array or complex type.
CT_MAYCONVERT = CT_ARRAY
CT_VOID = 4 # Void type.
CT_ENUM = 5 # Enumeration.
CT_HASSIZE = CT_ENUM # Last type where ct->size holds the actual size.
CT_FUNC = 6 # Function.
CT_TYPEDEF = 7 # Typedef.
CT_ATTRIB = 8 # Miscellaneous attributes.

# Common types.
CTID_NONE = 0
CTID_VOID = 1
CTID_CVOID = 2
CTID_BOOL = 3
CTID_CCHAR = 4
CTID_INT8 = 5
CTID_UINT8 = 6
CTID_INT16 = 7
CTID_UINT16 = 8
CTID_INT32 = 9
CTID_UINT32 = 10
CTID_INT64 = 11
CTID_UINT64 = 12
CTID_FLOAT = 13
CTID_DOUBLE = 14
CTID_COMPLEX_FLOAT = 15
CTID_COMPLEX_DOUBLE = 16
CTID_P_VOID = 17
CTID_P_CVOID = 18
CTID_P_CCHAR = 19
CTID_A_CCHAR = 20
CTID_CTYPEID = 21

# C type info flags.
CTF_BOOL       = 0x08000000 # Boolean: NUM, BITFIELD.
CTF_FP         = 0x04000000 # Floating-point: NUM.
CTF_CONST      = 0x02000000 # Const qualifier.
CTF_VOLATILE   = 0x01000000 # Volatile qualifier.
CTF_UNSIGNED   = 0x00800000 # Unsigned: NUM, BITFIELD.
CTF_LONG       = 0x00400000 # Long: NUM.
CTF_VLA        = 0x00100000 # Variable-length: ARRAY, STRUCT.
CTF_REF        = 0x00800000 # Reference: PTR.
CTF_VECTOR     = 0x08000000 # Vector: ARRAY.
CTF_COMPLEX    = 0x04000000 # Complex: ARRAY.
CTF_UNION      = 0x00800000 # Union: STRUCT.
CTF_VARARG     = 0x00800000 # Vararg: FUNC.
CTF_SSEREGPARM = 0x00400000 # SSE register parameters: FUNC.

CTMASK_ATTRIB = 255 # Max. 256 attributes.
CTSHIFT_ATTRIB = 16

# Attribute numbers.
CTA_NONE = 0 # Ignored attribute. Must be zero.
CTA_QUAL = 1 # Unmerged qualifiers.
CTA_ALIGN = 2 # Alignment override.
CTA_SUBTYPE = 3 # Transparent sub-type.
CTA_REDIR = 4 # Redirected symbol name.
CTA_BAD = 5 # To catch bad IDs.

CTSHIFT_NUM = 28
CTMASK_CID = 0x0000ffff
CTMASK_NUM = 0xf0000000 # Max. 16 type numbers.

# Special sizes.
CTSIZE_INVALID = 0xffffffff
DWORDSZ = 4
QWORDSZ = 8

def ctype_type(info):
    return info >> CTSHIFT_NUM

def ctype_attrib(info):
    return (info >> CTSHIFT_ATTRIB) & CTMASK_ATTRIB

def ctinfo(ct, flags):
    return (tou32(ct) << CTSHIFT_NUM) + flags

def ctype_isptr(info):
    return ctype_type(info) == CT_PTR

def ctype_iscomplex(info):
    return (info & (CTMASK_NUM | CTF_COMPLEX)) == ctinfo(CT_ARRAY, CTF_COMPLEX)

def ctype_isinteger(info):
    return (info & (CTMASK_NUM | CTF_BOOL | CTF_FP)) == ctinfo(CT_NUM, 0)

def ctype_isrefarray(info):
    return (info & (CTMASK_NUM | CTF_VECTOR | CTF_COMPLEX)) == \
            ctinfo(CT_ARRAY, 0)

def ctype_cid(info):
    return info & CTMASK_CID

def ctype_child(cts, ctype):
    return ctype_get(cts, ctype_cid(ctype['info']))

def cdataptr(cd):
    return cast('void *', (cd + 1))

def cdata_getptr(p, size):
    if LJ_64 and size == 4:
        return cast('void *', cast('uint32_t *', p)[0])
    else:
        return cast('void *', cast('uint64_t *', p)[0])

# Get C type ID for a C type.
def ctype_typeid(cts, ct):
    return ct - cts['tab']

def cdata_val_int64(cdata, ctype):
    info = ctype['info']
    isunsigned = info & CTF_UNSIGNED
    cdataval = cdataptr(cdata)
    valueptr = None
    usuffix = ''
    if isunsigned:
        usuffix = 'U'
        valueptr = cast('uint64_t *', cdataval)
    else:
        valueptr = cast('int64_t *', cdataval)

    return str(valueptr[0]) + usuffix + 'LL'

def cdata_val_complex(cdata, ctype):
    size = ctype['size']
    cdataval = cdataptr(cdata)
    casttype = None
    if size == QWORDSZ * 2:
        casttype = 'double *'
    else:
        assert size == DWORDSZ * 2, 'bad (complex float) size'
        casttype = 'float *'

    re = cast(casttype, cdataval)[0]
    im = cast(casttype, cdataval)[1]

    sign = '+' if im > 0 else ''
    return '{re}{sign}{im}i'.format(re = re, im = im, sign = sign)

def ctype_preplit(ctypestr, lit):
    # Prevent extra space in the end of the string.
    space = ' ' if ctypestr != '' else ''
    return lit + space + ctypestr

def ctype_prepqual(ctypestr, info):
    if (info & CTF_VOLATILE):
        ctypestr = ctype_preplit(ctypestr, 'volatile')
    if (info & CTF_CONST):
        ctypestr = ctype_preplit(ctypestr, 'const')
    return ctypestr

def ctype_preptype(cts, ctypestr, ctype, qual, tp):
    nameref = gcref(ctype['name'])
    if nameref:
        ctypestr =  ctype_preplit(ctypestr, re.sub('"', '', strdata(nameref)))
    else:
        ctypestr =  ctype_preplit(ctypestr, str(ctype_typeid(cts, ctype)))

    ctypestr = ctype_preplit(ctypestr, tp)
    ctypestr = ctype_prepqual(ctypestr, qual)
    return ctypestr

def ctype_prepnum(ctypestr, info, size):
    if info & CTF_BOOL:
        ctypestr = ctype_preplit(ctypestr, 'bool');
    elif info & CTF_FP:
        if size == QWORDSZ:
            ctypestr = ctype_preplit(ctypestr, 'double')
        elif size == DWORDSZ:
            ctypestr = ctype_preplit(ctypestr, 'float')
        else:
            assert size == QWORDSZ * 2, 'bad (long double) size'
            ctypestr = ctype_preplit(ctypestr, 'long double')
    elif size == 1:
        # TODO: Fixup char signess.
        if (info & CTF_UNSIGNED):
            ctypestr = ctype_preplit(ctypestr, 'unsigned char')
        else:
            ctypestr = ctype_preplit(ctypestr, 'char')
    elif size < 8:
        if size == 4:
            ctypestr = ctype_preplit(ctypestr, 'int')
        else:
            assert size == DWORDSZ / 2, 'bad (short) size'
            ctypestr = ctype_preplit(ctypestr, 'short')

        if (info & CTF_UNSIGNED):
            ctypestr = ctype_preplit(ctypestr, 'unsigned')
    else:
        size_t = '{u}int{sz}_t'.format(
            u = 'u' if info & CTF_UNSIGNED else '',
            sz = size * 8,
        )
        ctypestr = ctype_preplit(ctypestr, size_t)
    return ctypestr

def ctype_repr(cts, id):
    ctype = ctype_get(cts, id)
    ctypestr = ''
    qual = 0
    ptrto = 0
    while True:
        info = ctype['info']
        size = ctype['size']
        ctp = ctype_type(info)
        if ctp == CT_NUM:
            ctypestr = ctype_prepnum(ctypestr, info, size)
            return ctype_prepqual(ctypestr, qual | info)
        elif ctp == CT_VOID:
            ctypestr = ctype_preplit(ctypestr, 'void')
            return ctype_prepqual(ctypestr, qual | info)
        elif ctp == CT_STRUCT:
            tp = 'union' if (info & CTF_UNION) else 'struct'
            return ctype_preptype(cts, ctypestr, ctype, qual, tp)
        elif ctp == CT_ENUM:
            if id == CTID_CTYPEID:
                return ctype_preplit(ctypestr, 'ctype')
            return ctype_preptype(cts, ctypestr, ctype, qual, 'enum')
        elif ctp == CT_ATTRIB:
            if ctype_attrib(info) == CTA_QUAL:
                qual |= size
        elif ctp == CT_PTR:
            if info & CTF_REF:
                ctypestr = ctype_preplit(ctypestr, '&')
            else:
                ctypestr = ctype_prepqual(ctypestr, qual | info)
                if LJ_64 and size == 4:
                    ctypestr = ctype_preplit(ctypestr, '__ptr32')
                ctypestr = ctype_preplit(ctypestr, '*')
            qual = 0;
            ptrto = 1;
        elif ctp == CT_ARRAY:
            if ctype_isrefarray(info):
                if ptrto:
                    ptrto = 0
                    ctypestr = '(' + ctypestr + ')'
                arrsize = ''
                if size != CTSIZE_INVALID:
                    child_size = ctype_child(cts, ctype)['size']
                    arrsize = str(size / child_size if child_size > 0 else 0)
                elif info & CTF_VLA:
                    arrsize = '?'
                ctypestr = ctypestr + '[{}]'.format(arrsize)
            elif ctype_iscomplex(info):
                if size == DWORDSZ * 2:
                    ctypestr = ctype_preplit(ctypestr, 'float')
                else:
                    assert size == QWORDSZ * 2, 'bad (complex double) size'
                return ctype_preplit(ctypestr, 'complex')
            else:
                ctypestr = ctype_preplit(
                    '__attribute__((vector_size({})))'.format(size)
                )
        elif ctp == CT_FUNC:
            if ptrto:
                ptrto = 0
                ctypestr = '(' + ctypestr + ')'
            ctypestr += '()'

        ctype = ctype_child(cts, ctype)

    return 'NIY'

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
    cdata = cast('struct GCcdata *', gcobj)
    cts = ctype_ctsG(G(L()))

    cid = cdata['ctypeid']
    ctype = ctype_get(cts, cid)
    info = ctype['info']
    size = ctype['size']
    name = ctype_repr(cts, cid)
    value = ''

    if ctype_iscomplex(info):
        value = cdata_val_complex(cdata, ctype)
    elif size == 8 and ctype_isinteger(info):
        value = cdata_val_int64(cdata, ctype)
    else:
        value = cdataptr(cdata)
        if ctype_isptr(info):
            value = cdata_getptr(value, size)

    return 'cdata @ {addr} [{id}] <{name}> {value}'.format(
        addr = strx64(gcobj),
        id = cid,
        name = name,
        value = value,
    )

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

    res = '{addr}{padding} [ {B}{T}{M}] VALUE: {value}'.format(
        addr = strx64(slot),
        padding = PADDING,
        B = 'B' if slot == base else ' ',
        T = 'T' if slot == top else ' ',
        M = 'M' if slot == mref('TValue *', L['maxstack']) else ' ',
        value = dump_tvalue(slot),
    )
    return res

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


def dump_call_func(trace, callop):
    ctype = ''
    if callop > 0:
        ir = trace['ir'][REF_BIAS + callop]
        if IRTYPES[irt_type(ir['t'])] == 'nil': # nil == CARG(func, ctype)
            callop = int(ir['op1']) - REF_BIAS
            cts = ctype_ctsG(G(L()))
            cdt_idx_irk = trace['ir'][ir['op2']]
            assert IRS[cdt_idx_irk['o']]['name'] == 'KINT', \
                   'unexpected IR for ctype storage'
            ctype_idx = cdt_idx_irk['i']
            ctype = '<{}>'.format(ctype_repr(cts, ctype_idx))

    func_str = ''
    if callop < 0:
        irk = trace['ir'][REF_BIAS + callop]
        assert IRS[irk['o']]['name'] == 'KINT64', \
               'unexpected IR for FFI function storage'
        func_addr = int(ir_kint64(irk)['u64'])
        # TODO: symbol demangling?
        func_str = '[{:#x}]'.format(func_addr)
    else:
        func_str = '[{:04d}]'.format(callop)

    return func_str, ctype

def dump_call_args(trace, ins):
    if ins < 0:
        return '{{{}}}'.format(dump_irk(trace, ins))
    else:
        ir = trace['ir'][REF_BIAS + ins]
        irname = IRS[ir['o']]['name']
        if irname == 'CARG':
            last_arg = ''
            args = dump_call_args(trace, int(ir['op1']) - REF_BIAS)
            op2 = int(ir['op2']) - REF_BIAS
            if op2 < 0:
                last_arg = '{{{}}}'.format(dump_irk(trace, op2))
            else:
                last_arg = '{{{:04d}}}'.format(op2)
            return args + ', ' + last_arg
        else:
            return '{{{:04d}}}'.format(ins)

# Special FP constant.
CONST_BIAS = 2 ** 52 + 2 ** 51

def dump_irk(trace, idx):
    ref = idx + REF_BIAS
    assert ref >= trace['nk'] and ref < REF_BIAS, 'bad constant in IR dump'
    irins = trace['ir'][ref]
    ir = IRS[irins['o']]
    irname = ir['name']
    slot = ''
    if irname == 'KSLOT':
        slot = ' KSLOT: @{}'.format(int(irins['op2']))
        irins = trace['ir'][irins['op1']]
        ir = IRS[irins['o']]
        irname = ir['name']

    irtype = irins['t']
    irt = irt_type(irtype)
    if irname == 'KPRI':
        typename = typenames(irt_toitype(irtype))
        # Trivial dump for primitives.
        irk = tv_dumpers.get(typename, dump_lj_tv_invalid)(0)
    elif irname == 'KINT':
        irk = 'integer {}'.format(cast('int32_t', irins['i']))
    elif irname == 'KGC':
        typename = typenames(irt_toitype(irtype))
        irk = gco_dumpers.get(typename, dump_lj_gco_invalid)(ir_kgc(irins))
    elif irname == 'KKPTR':
        addr = ir_kptr(irins)
        if addr == G(L())['nilnode'].address:
            return '[g->nilnode]' + slot
        irk = '[{}]'.format(strx64(addr))
    elif irname == 'KPTR':
        irk = '[{}]'.format(strx64(ir_kptr(irins)))
    elif irname == 'KNULL':
        irk = 'NULL'
    elif irname == 'KNUM':
        tv_num = ir_knum(irins)
        if float(tv_num['n']) == CONST_BIAS:
            return 'bias'
        irk = dump_lj_tv_numx(tv_num)
    elif irname == 'KINT64':
        irk = 'int64_t {}'.format(cast('int64_t', int(ir_kint64(irins)['u64'])))
    else:
        return 'Unknown IRK: ' + irname
    return irk + slot

def dump_irins(irins, trace=None):
    irop = irins['o']
    if irop >= len(IRS):
        return 'INVALID'

    ir = IRS[irop]
    irt = irins['t']
    irname = ir['name']
    is_sinksunk = irins['r'] == RID_SINK or irins['r'] == RID_SUNK
    flags = '{is_sinksunk}{is_marked}{is_guard}{is_phi}'.format(
        # Sink flag should be the first to match sink slots during
        # the dump of registers.
        is_sinksunk = '}' if is_sinksunk else ' ',
        is_marked = '!' if irt_ismarked(irt) else ' ',
        is_guard = '>' if irt_isguard(irt) else ' ',
        is_phi = '+' if irt_isphi(irt) else ' '
    )

    if not trace:
        g = G(L(None))
        compiling = jit_state(g) != 'IDLE'
        assert compiling, 'attempt to dump IR for J.cur trace in bad VM state'
        trace = J(g)['cur']

    left = ''
    right = ''
    lisref = ir['left'] == 'ref'
    risref = ir['right'] == 'ref'
    op1 = int((irins['op1'] - REF_BIAS) if lisref else irins['op1'])
    op2 = int((irins['op2'] - REF_BIAS) if risref else irins['op2'])

    skip_right = False
    if re.match('CALL', irname):
        ctype = ''
        args = ''
        if ir['right'] == 'lit':
            func = IR_CALLS[op2]
        else:
            func, ctype = dump_call_func(trace, op2)

        if op1 != -1:
            args = dump_call_args(trace, int(op1))

        return '{flags} {type} {name:6} [{mode:2}] {f}({args}) {ct}\n'.format(
            flags = flags,
            name = irname,
            mode = ir['mode'],
            type = IRTYPES[irt_type(irt)],
            ct = ctype,
            args = args,
            f = func,
        )
    elif irname == 'CNEW' and op2 == -1:
        left = dump_irk(trace, op1)
        skip_right = True
    elif ir['left']:
        if op1 < 0:
            left = dump_irk(trace, op1)
        elif ir['left'] == 'cst':
            idx = irins - trace['ir'][REF_BIAS].address
            left = dump_irk(trace, idx)
        else:
            left = ('{:04d}' if lisref else '#{:<3d}').format(op1)

        if ir['right']:
            if ir['right'] == 'lit':
                litname = IR_LITNAMES.get(irname, None)
                if litname:
                    # Try to handle `lj_ir_ggfload()`.
                    ggfname = None
                    if irname == 'FLOAD' and left == 'nil' \
                       and op2 >= len(IRFIELDS):
                        ggfname = ggfname_by_offset(op2 << 2)

                    if ggfname:
                        right = ggfname
                    else:
                        right = litname(op2)
                elif irname == 'UREFO' or irname == 'UREFC':
                    right = '#{:<3d}'.format(op2 >> 8)
                else:
                   right = '#{:<3d}'.format(op2)
            elif op2 < 0:
                right = dump_irk(trace, op2)
            else:
                right = ('{:04d}').format(op2)

    typename = ''
    if irname == 'LOOP':
        typename = '---'
    elif irname == 'NOP':
        typename = '   '
    else:
        typename = IRTYPES[irt_type(irt)]

    return '{flags} {type} {name:6} [{mode:2}] {left:<9s} {right}\n'.format(
        flags = flags,
        name = irname,
        mode = ir['mode'],
        type = typename,
        left = (ir['left'] + ': ' + left) if ir['left'] else '',
        right = (ir['right'] + ': ' + right) if ir['right'] \
                                                and not skip_right else '',
    )

def dump_snap(trace, snapno, snap):
    dump = 'SNAP   #{:<3d} ['.format(snapno)
    snap_map = trace['snapmap'][snap['mapofs']].address
    snap_entry_num = 0
    for slot in range(0, snap['nslots']):
        dump += ' '
        snap_entry = int(snap_map[snap_entry_num])
        if snap_entry_num < snap['nent'] and snap_entry >> TREF_SHIFT == slot:
            snap_entry_num += 1
            ref = int((snap_entry & TREF_REFMASK) - REF_BIAS)
            if ref < 0:
                if int(snap_entry) == 0x1057fff:
                    dump += '----'
                    continue
                elif (snap_entry & TREF_CONT):
                    dump += 'contpc'
                elif (snap_entry & TREF_FRAME):
                    dump += 'ftsz '
                else:
                    dump += '{{{const}}}'.format(const = dump_irk(trace, ref))
            elif snap_entry & SNAP_SOFTFPNUM:
                dump += '{:04d}/{:04d}'.format(ref, ref + 1)
            else:
                dump += '{:04d}'.format(ref)

            if snap_entry & SNAP_FRAME:
                dump += '|'
        else:
            dump += '----'

    dump += ' ]\n'
    return dump

def dump_sink_slot(rid, spill, ins_number):
    assert rid == RID_SINK or rid == RID_SUNK, 'incorrect rid in sink dump'
    tp = 'sink' if rid == RID_SINK else 'sunk'
    return '{{{}'.format(tp) if spill == RID_INIT or spill == SPS_NONE \
           else '{{{:04d}'.format(int(ins_number - spill))

def dump_regsp(irins, ins_number):
    rid = irins['r']
    spill = irins['s']
    if rid == RID_SINK or rid == RID_SUNK:
        return dump_sink_slot(rid, spill, ins_number)
    elif irins['prev'] > 255:
        return '[{:#05x}]'.format(int(spill * 4))
    elif rid < 128:
        return regname(rid)
    else:
        return ''

def dump_trace(trace, flags):
    dump = 'Trace {num} start\n\tproto: {start_pt}\n\tBC: {start_bc}\n'.format(
        num = trace['traceno'],
        start_pt = gcref(trace['startpt']),
        start_bc = mref('BCIns *', trace['startpc']),
    )

    nins = trace['nins'] - REF_BIAS
    dump += '---- TRACE IR\n'
    nsnap = 0
    snap = trace['snap'][nsnap]
    snapref = snap['ref']
    for irnum in range(1, nins):
        irref = REF_BIAS + irnum
        if 's' in flags and irref >= snapref and nsnap < trace['nsnap']:
            dump += '....          '
            if 'r' in flags:
                dump += ' ' * 7
            dump += dump_snap(trace, nsnap, snap)
            nsnap += 1
            snap = trace['snap'][nsnap]
            snapref = snap['ref']
        dump += '{:04d} '.format(irnum)
        if 'r' in flags:
            dump += '{:>7}'.format(dump_regsp(trace['ir'][irref], irnum))
        dump += dump_irins(trace['ir'][irref], trace)
    return dump

def dump_tref(tref):
    return '[{F}{C}] {type} {ref:#x}'.format(
        F = 'F' if tref & TREF_FRAME else ' ',
        C = 'C' if tref & TREF_CONT  else ' ',
        type = IRTYPES[tref_type(tref)],
        ref = tref_ref(tref)
    )

def dump_jslots(coroutine):
    l = L(None)
    g = G(l or coroutine)
    vmst = vm_state(g)
    if not (vmst == 'RECORD' or vmst == 'OPT' or vmst == 'ASM'):
        raise gdb.GdbError('Attempt to dump jslots outside of trace recording')
    j = J(g)

    dump = ''
    maxslot = j['baseslot'] + j['maxslot']
    first_base_slot = 1 + LJ_FR2
    for n in reversed(range(first_base_slot, maxslot)):
        tref = j['slot'][n]
        ref = tref_ref(tref)
        address = tref.address
        dump += '{addr} {nslot:04d} {base:1s} {tref}{const}\n'.format(
            addr = address,
            base = 'B' if address == j['base'] else ' ',
            nslot = n,
            tref = dump_tref(tref),
            const = ' ' + dump_irk(j['cur'], ref - REF_BIAS) \
                    if ref != 0 and ref < REF_BIAS else ''
        )
    return dump

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
            'LJ_64: {LJ_64}, '
            'LJ_GC64: {LJ_GC64}, '
            'LJ_DUALNUM: {LJ_DUALNUM}\n'
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

class LJDumpGCo(LJBase):
    '''
lj-gco <TValue *>

The command receives a pointer to <gc> (GCobj address) and dumps
the type and some info related to it.


Whether the type of the given address differs from the listed above, then
error message occurs.
    '''

    def invoke(self, arg, from_tty):
        gco = cast('GCobj *', parse_arg(arg))
        gdb.write('{}\n'.format(dump_gcobj(gco)))


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

class LJDumpIR(LJBase):
    '''
lj-ir <IRIns *>

    '''

    def invoke(self, arg, from_tty):
        gdb.write('{}'.format(dump_irins(cast('IRIns *', parse_arg(arg)))))

class LJDumpTrace(LJBase):
    '''
lj-trace <GCtrace *>

    '''

    def invoke(self, arg, from_tty):
        arg, flags = extract_flags(arg, 'rs')
        gdb.write('{}'.format(dump_trace(
            cast('GCtrace *', parse_arg(arg)),
            flags
        )))

class LJDumpJSlots(LJBase):
    '''
lj-jslots <GCtrace *>
    '''

    def invoke(self, arg, from_tty):
        gdb.write('{}'.format(dump_jslots(cast('lua_State *', parse_arg(arg)))))


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
        'lj-gco': LJDumpGCo,
        'lj-bc': LJDumpBC,
        'lj-proto': LJDumpProto,
        'lj-func': LJDumpFunc,
        'lj-ir': LJDumpIR,
        'lj-trace': LJDumpTrace,
        'lj-jslots': LJDumpJSlots,
    })

load(None)
