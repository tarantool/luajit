do --- Too many results to unpack.
  local j = 1e4
  local co = coroutine.create(function()
    local t = {}
    for i = 1, j do
      t[i] = i
    end
    return unpack(t)
  end)
  local ok, err = coroutine.resume(co)
  assert(not ok and string.find(err, "unpack"))
end
