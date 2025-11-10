local caught

local function gcmeta()
  if caught ~= "end" then
    -- This may point to the wrong instruction if in a JIT trace.
    -- But there's no guarantee if, when or where any GC steps occur.
    caught = true
  end
end

local function testgc(mm, f)
  collectgarbage()
  caught = false
  local u = newproxy(true)
  getmetatable(u).__gc = gcmeta
  u = nil
  for i = 1, 1e7 do
    f(i)
    -- This check may be hoisted. __gc is not supposed to have side-effects.
    if caught then break end
  end
  if not caught then
    error(mm.." metamethod not called", 2)
  end
end

do --- Test __gc metamethod info
  -- Do not run this test unless the JIT compiler is turned off.
  local jit_need_restore = false
  if jit and jit.status and jit.status() then
    jit_need_restore = true
    jit.off()
  end

  local x
  testgc("__gc", function(i) x = {} end)
  testgc("__gc", function(i) x = {1} end)
  testgc("__gc", function(i) x = function() end end)
  testgc("__concat", function(i) x = i.."" end)

  caught = "end"
  if jit_need_restore then
     jit.on()
  end
end
