local ffi = require("ffi")

ffi.cdef[[
  int fork(void);
  unsigned int sleep(unsigned int seconds);
  int waitpid(int pid, int *status, int options);
]]

local pid = ffi.C.fork()

if pid == 0 then
  -- child.
  ffi.C.sleep(10)
elseif pid > 0 then
  -- parent.
  local status = ffi.new("int[1]")
  -- wait() system call: it restarts after signal is handled
  -- if SA_RESTART flag is set for the handler in sigaction()
  -- or if old signal() is used and it's OS specific
  -- implementation is BSD-aware.
  ffi.C.waitpid(pid, status, 0)
else
  -- fork() failed.
  os.exit(1)
end
