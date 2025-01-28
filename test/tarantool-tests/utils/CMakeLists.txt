list(APPEND tests
  lj-1166-error-stitch-oom-ir-buff.test.lua
  lj-1166-error-stitch-oom-snap-buff.test.lua
)
BuildTestCLib(allocinject allocinject.c "${tests}")
