-- Use the default LuaJIT globals.
std = 'luajit'

-- These files are inherited from the vanilla LuaJIT and need to
-- be coherent with the upstream.
exclude_files = {
  'dynasm/',
  'src/',
  'test/LuaJIT-tests/',
}
