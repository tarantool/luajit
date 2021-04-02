local utils = require('utils')

-- Disabled on *BSD due to #4819.
utils.skipcond(jit.os == 'BSD', 'Disabled due to #4819')

utils.selfrun(arg, {
  {
    arg = {
      1, -- hotloop (arg[1])
      1, -- trigger (arg[2])
    },
    msg = 'Trace is aborted',
    res = 'OK',
    test = 'is',
  },
  {
    arg = {
      1, -- hotloop (arg[1])
      2, -- trigger (arg[2])
    },
    msg = 'Trace is recorded',
    res = 'JIT mode change is detected while executing the trace',
    test = 'like',
  },
})

----- Test payload. ----------------------------------------------

local cfg = {
  hotloop = arg[1] or 1,
  trigger = arg[2] or 1,
}

local ffi = require('ffi')
local ffiflush = ffi.load('libflush')
ffi.cdef('void flush(struct flush *state, int i)')

-- Save the current coroutine and set the value to trigger
-- <flush> call the Lua routine instead of C implementation.
local flush = require('libflush')(cfg.trigger)

-- Depending on trigger and hotloop values the following contexts
-- are possible:
-- * if trigger <= hotloop -> trace recording is aborted
-- * if trigger >  hotloop -> trace is recorded but execution
--   leads to panic
jit.opt.start("3", string.format("hotloop=%d", cfg.hotloop))

for i = 0, cfg.trigger + cfg.hotloop do
  ffiflush.flush(flush, i)
end
-- Panic didn't occur earlier.
print('OK')
