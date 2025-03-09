local ffi = require('ffi')

ffi.cdef[[
  int pipe(int *fds);
  int getpid(void);
  long read(int fd, void *buf, size_t count);
  unsigned int alarm(unsigned int seconds);
]]

-- local fds = ffi.new('int[2]')
-- assert(ffi.C.pipe(fds) == 0)

-- Fail instead of hanging forever if SIGINT does not break
-- the call. (SIGALRM isn't handled by CLI.)
ffi.C.alarm(10)

-- The CLI installs the SIGINT handler before the script
-- starts, so this line is the readiness marker for the test.
local MARKER = 'CHILD_PID:'
io.write(MARKER, ffi.C.getpid(), '\n')
io.flush()

-- The script runs via 'popen()', so the stdin is connected
-- to the write end of the pipe in the parent process.
-- Block in read(2) until SIGINT. Without SA_RESTART it returns
-- EINTR and the CLI runs the Lua hook, which raises
-- "interrupted!".
-- ffi.C.read(fds[0], ffi.new('char[1]'), 1)
local x = io.read()
io.write('read: '..x)
io.flush()