local tap = require('tap')
local test = tap.test('lj-840-fix-hrefk-opt'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Test requires GC64 mode enabled'] = not require('ffi').abi('gc64'),
})

test:plan(1)

local ffi = require('ffi')
local table_new = require('table.new')

ffi.cdef[[
unsigned long long strtoull(const char *restrict str, char **restrict endptr, int base);

typedef struct GCtab {
    uint64_t nextgc;
    uint8_t marked;
    uint8_t gct;
    uint8_t nomm;
    int8_t colo;
    uint64_t array;
    uint64_t gclist;
    uint64_t metatable;
    uint64_t node;
    uint32_t asize;
    uint32_t hmask;
    uint64_t freetop;
} GCtab;
]]

local function get_table_hash_pointer(obj)
    assert(type(obj) == 'table')
    local str_ptr = string.format('%p', obj)
    local uint64_ptr = ffi.C.strtoull(str_ptr, nil, 0)
    return ffi.cast('GCtab *', uint64_ptr).node
end

local function is_distance_enough(tab)
    local nil_node = get_table_hash_pointer({})
    local ptr = get_table_hash_pointer(tab)
    -- node has a type uint64_t, but we cast it to uint32_t to avoid oom.
    local diff = tonumber(ffi.cast('uint32_t', nil_node - ptr))
    return diff <= 65535 * 24
end

local function prepare_table()
    local tbl = table_new(0, 1)
    local root
    while not is_distance_enough(tbl) do
        tbl.next = root
        root = tbl
        tbl = table_new(0, 2*10^4)
    end
    return tbl
end


-- Record indexed key lookup, rec_idx_key().
local function get_n(tbl)
    local n
    for _ = 1, 3 do
        n = tbl.n
    end
    return n
end

-- Do not compile, please.
jit.off()
local tbl1 = prepare_table()
jit.on()

jit.opt.start('hotloop=1')
get_n(tbl1)
-- Constant value of any type.
local val = 1
assert(get_n({n = val}) == 1, "n has incorrect value")

-- test:ok(get_n({n = 1}) == 1)
-- os.exit(test:check() and 0 or 1)
