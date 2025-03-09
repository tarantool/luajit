local ffi = require('ffi')

ffi.cdef[[
  int pipe(int *fds);
  int getpid(void);
  long read(int fd, void *buf, size_t count);
  unsigned int alarm(unsigned int seconds);
]]

-- The script runs via 'popen()' with closed pipe read-end,
-- and the stdin is not guaranteed to be connected somewhere.
-- Reading from it may result in EOF.
-- So, establish the new pipe, which read-end would block.
local fds = ffi.new('int[2]')
assert(ffi.C.pipe(fds) == 0)

-- Fail instead of hanging forever if SIGINT does not break
-- the call. (SIGALRM isn't handled by CLI.)
ffi.C.alarm(10)

-- The CLI installs the SIGINT handler before the script
-- starts, so this line is the readiness marker for the test.
local MARKER = 'CHILD_PID:'
io.write(MARKER, ffi.C.getpid(), '\n')
io.flush()

-- Block in read(2) until SIGINT. Without SA_RESTART it returns
-- EINTR and the CLI runs the Lua hook, which raises
-- "interrupted!".
ffi.C.read(fds[0], ffi.new('char[1]'), 1)
