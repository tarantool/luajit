local ffi = require('ffi')

ffi.cdef[[
typedef struct {
    uint8_t a;
    uint8_t b;
} TestStruct;
]]

local obj = ffi.new("TestStruct")
local intPtr = ffi.cast("uint64_t *", obj)

-- mem dump: ... RZ 00 00 02 RZ ... \\ RZ - redzone
--                        ^
--                        |
--                       ptr

-- error (right RZ)
print(intPtr[2])