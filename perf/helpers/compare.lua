local json = require('cjson')

local abs, exp, log, max = math.abs, math.exp, math.log, math.max
local find, format = string.find, string.format
local match, rep, sub = string.match, string.rep, string.sub
local table_insert, table_remove = table.insert, table.remove
local table_sort = table.sort

local assert = assert
local ipairs, print, setmetatable = ipairs, print, setmetatable
local tonumber, type = tonumber, type

local HELP_MSG = [[
  --alpha=num            Significance level alpha. If the calculated
                         result relative difference is below this
                         value the test results are considered the same.
                         (default: 0.05)
  --changes_only, -c     Display only benches that differ significantly.
  --display_aggregates_only, -a
                         Display only the geomean difference for all
                         benchmarks.
  --dump_to_json=file, -d=file
                         Dump benchmark comparison output to the given
                         file in JSON format.
  --hide_aggregates, -i  Do not show aggregates and their differences.
  --no_color             Do not use colors in the terminal output.
  --help, -h             Display this message and exit.
]]

local EXIT_FAILURE = 1

local function fatal(...)
  io.stderr:write(...)
  os.exit(EXIT_FAILURE)
end

local function warn(...)
  io.stderr:write(...)
end

local function usage()
  local header = 'USAGE: luajit compare.lua [options] baseline contender\n'
  fatal(header, HELP_MSG)
end

local alpha = 0.05
local function set_alpha(val)
  alpha = tonumber(val)
  assert(alpha, format('invalid alpha value: %s', val))
end

local clr = {
  BRGREEN = '\027[92m',
  GREEN = '\027[32m',
  RED = '\027[31m',
  WHITE = '\027[97m',
  CLEAR = '\027[m',
}

local colorless_pallete = setmetatable({}, {__index = function() return '' end})

local function set_nocolor()
  clr = colorless_pallete
end

local output
local function set_output(outname)
  output = assert(io.open(outname, 'w+'))
end

local aggregates_only = false
local hide_aggregates = false
local AGGR_MSG = 'Do not use display_aggregates_only and hide_aggregates' ..
                 'flags together:\n'

local function set_aggregates_only()
  if hide_aggregates then
    fatal(AGGR_MSG, HELP_MSG)
  end
  aggregates_only = true
end

local function set_hide_aggregates()
  if aggregates_only then
    fatal(AGGR_MSG, HELP_MSG)
  end
  hide_aggregates = true
end

local changes_only = false
local function set_changes_only()
  changes_only = true
end

local function unrecognized_option(optname, dashes)
  local fullname = dashes .. (optname or '=')
  fatal(format('unrecognized command-line flag: %s\n', fullname), HELP_MSG)
end

local function unrecognized_long_option(_, optname)
  unrecognized_option(optname, '--')
end

local function unrecognized_short_option(_, optname)
  unrecognized_option(optname, '-')
end

local SHORT_OPTS = setmetatable({
  ['a'] = set_aggregates_only,
  ['c'] = set_changes_only,
  ['d'] = set_output,
  ['i'] = set_hide_aggregates,
  ['h'] = usage,
}, {__index = unrecognized_short_option})

local LONG_OPTS = setmetatable({
  ['alpha'] = set_alpha,
  ['changes_only'] = set_changes_only,
  ['display_aggregates_only'] = set_aggregates_only,
  ['dump_to_json'] = set_output,
  ['hide_aggregates'] = set_hide_aggregates,
  ['no_color'] = set_nocolor,
  ['help'] = usage,
}, {__index = unrecognized_long_option})

local function is_option(str)
  return type(str) == 'string' and sub(str, 1, 1) == '-' and str ~= '-'
end

local function parse_long_option(a)
  local opt_name, opt_value
  -- Remove dashes.
  local opt = sub(a, 3)
  -- --option=value
  if find(opt, '=', 1, true) then
    -- May match empty option name and/or value.
    opt_name, opt_value = match(opt, '^([^=]+)=(.*)$')
  else
    -- --option without value
    opt_name = opt
  end
  return opt_name, opt_value
end

local function handle_short_option(a)
  -- Remove the dash.
  local opt = sub(a, 2)
  while sub(opt, 1, 1) ~= '' do
    local opt_name = sub(opt, 1, 1)
    if sub(opt, 2, 2) == '=' then
      -- -o=value
      local opt_value = sub(opt, 3)
      SHORT_OPTS[opt_name](opt_value)
      return
    end
    SHORT_OPTS[opt_name]()
    -- Proceed with the remaining short options.
    opt = sub(opt, 2)
  end
end

local function handle_option(a)
  if sub(a, 1, 2) == '--' then
    local opt_name, opt_value = parse_long_option(a)
    LONG_OPTS[opt_name](opt_value)
  else
    handle_short_option(a)
  end
end

-- Process the options and update the script context.
local function argparse(arg)
  local n = 1
  while n <= #arg do
    local a = arg[n]
    if is_option(a) then
      table_remove(arg, n)
      handle_option(a)
    else
      -- Just ignore it.
      n = n + 1
    end
  end
end

------------ File system helpers. --------------------------------

-- Simple checker if the given path is a directory.
local function isdir(path)
  local fh = io.open(path)
  -- Can't use read on directories.
  local err, msg = fh:read(1)
  fh:close()
  if not err and match(msg, 'Is a directory') then
    return true
  else
    return false
  end
end

-- Not very robust, but OK for our needs.
local function listdir(path)
  local handle = io.popen('ls -1 ' .. path)

  local files = {}
  for file in handle:lines() do
    table_insert(files, file)
  end

  return files
end

local function read_all(file)
  local fh = assert(io.open(file, 'rb'))
  local content = fh:read('*all')
  fh:close()
  return content
end

------------ Comparison of the results. --------------------------

-- Compare to lists and return intersection of them.
-- Print warning if any element is missing.
local function intersection(a, b, msga, msgb)
  local intersect = {}
  -- Scan tables, with sorted elements.
  -- If any element missing (this element is less than the nearest
  -- from another list), print warning.
  table_sort(a)
  table_sort(b)
  local ai, bi = 1, 1
  while ai <= #a or bi <= #b do
    if a[ai] == b[bi] then
      table_insert(intersect, a[ai])
      ai = ai + 1
      bi = bi + 1
    elseif bi > #b or (ai < #a and a[ai] < b[bi]) then
      warn(format(msga, a[ai]))
      ai = ai + 1
    else
      assert(ai > #a or (bi < #b and a[ai] > b[bi]), 'incorrect intersection')
      warn(format(msgb, b[bi]))
      bi = bi + 1
    end
  end
  return intersect
end

-- Calculate geomean for the given bench names.
local function gmean(results, list)
  local n = #list
  if n == 1 then
    return results[list[1]]
  end
  local gmn = 0
  -- Use Log-Transform calculation to avoid infinite values.
  for i = 1, n do
    gmn = gmn + log(results[list[i]])
  end
  gmn = gmn / n
  return exp(gmn)
end

-- Return relative change between baseline and contender.
local function calculate_change(base, cont)
  return (cont - base) / base
end

-- Convert array of benchmarks to the simple map:
-- benchname -> metric value.
local function bench_map(benches)
  local map = {}
  for _, bench in ipairs(benches) do
    map[bench.name] = tonumber(bench.items_per_second)
  end
  return map
end

-- Create a list of benchmark names for intersection.
local function bench_list(benches)
  local list = {}
  for _, bench in ipairs(benches) do
    table_insert(list, bench.name)
  end
  return list
end

-- XXX: Return result serialized in the same format as compare.py
-- in Google Benchmark. Not sure that we really need this
-- compatibility.
local function serialize_result(name, base, cont, run_type, aggregate)
  local change = calculate_change(base, cont)
  return {
      name = name,
      measurements = {{
        rps = change,
        items_per_second = cont,
        items_per_second_other = base,
      }},
      run_type = run_type or 'iteration',
      aggregate_name = aggregate or '',
  }, not changes_only or abs(change) > alpha
end

local function compare_benchmarks(baseline_bench, contender_bench)
  local base_benches = json.decode(read_all(baseline_bench)).benchmarks
  local cont_benches = json.decode(read_all(contender_bench)).benchmarks
  local base_map = bench_map(base_benches)
  local cont_map = bench_map(cont_benches)
  local benchnames = intersection(
    bench_list(base_benches), bench_list(cont_benches),
    'Contender benchmark has no bench %s, it is ignored.\n',
    'Baseline benchmark has no bench %s, it is ignored.\n'
  )
  local compare_results = {}
  local bench_differs = not changes_only
  if not aggregates_only then
    for _, benchname in ipairs(benchnames) do
      local base_res = base_map[benchname]
      local cont_res = cont_map[benchname]
      local cmp, displayed = serialize_result(benchname, base_res, cont_res)
      if displayed then
        table_insert(compare_results, cmp)
        bench_differs = true
      end
    end
  end
  if not hide_aggregates then
    local base_gmean = gmean(base_map, benchnames)
    local cont_gmean = gmean(cont_map, benchnames)
    local cmp, displayed = serialize_result('OVERALL_GEOMEAN',
      base_gmean, cont_gmean, 'aggregate', 'geomean'
    )
    if displayed then
      table_insert(compare_results, cmp)
      bench_differs = true
    end
  end
  return compare_results, bench_differs
end

local function compare_benchmarks_sets(baseline_dir, contender_dir)
  -- Compare any matched files in the directories.
  local baseline_benches = listdir(baseline_dir)
  local contender_benches = listdir(contender_dir)
  local same_benches = intersection(baseline_benches, contender_benches,
    'Contender directory has no file %s, it is ignored.\n',
    'Baseline directory has no file %s, it is ignored.\n'
  )
  local total_results = {}
  for _, benchname in ipairs(same_benches) do
    local benches, displayed = compare_benchmarks(
      baseline_dir .. '/' .. benchname,
      contender_dir .. '/' .. benchname
    )
    if displayed then
      table_insert(total_results, {
        name = benchname,
        benches = benches,
      })
    end
  end
  return total_results
end

------------ Output and formatting. ------------------------------

local function format_ips(ips)
  local ips_str
  if ips / 1e6 > 1 then
    ips_str = format('%.2fM/s', ips / 1e6)
  elseif ips / 1e3 > 1 then
    ips_str = format('%.2fk/s', ips / 1e3)
  else
    ips_str = format('%d/s', ips)
  end
  return ips_str
end

-- Create header of report and format line for bench statistics
-- (includes %s for colorizing chunks).
local function create_fmt_lines(benches)
  local header = 'Benchmark'
  local HDR_OFFSET = 12
  local maxname = #header
  for _, bench in ipairs(benches) do
    maxname = max(maxname, #bench.name)
  end
  header = header .. rep(' ', HDR_OFFSET + maxname - #header) ..
    'items_per_second       IPS New       IPS Old  '
  local format_name = '%s%- ' .. maxname .. 's%s'
  local format_line = format_name .. rep(' ', HDR_OFFSET) ..
    '%s%-+23.2f%s%-14s%-14s'
  header = header .. '\n' .. rep('-', #header)
  return header, format_line
end

local function diff_color(p)
  if p <= -alpha then
    return clr.RED
  elseif p >= alpha then
    return clr.GREEN
  else
    return clr.WHITE
  end
end

local function print_compare(fmt, bench)
  local m = bench.measurements[1]
  print(format(fmt,
        clr.BRGREEN, bench.name, clr.CLEAR,
        diff_color(m.rps), m.rps, clr.CLEAR,
        format_ips(m.items_per_second), format_ips(m.items_per_second_other)
  ))
end

local function output_results(benches, bpath, cpath)
  if output then
    output:write(json.encode(benches))
  else
    local header, format_line = create_fmt_lines(benches)
    print(format('Comparing %s to %s', bpath, cpath))
    print(header)
    for _, bench in ipairs(benches) do
      print_compare(format_line, bench)
    end
    -- Empty line to separate different files.
    print()
  end
end

local function output_sets_results(res, bpath, cpath)
  if output then
    output:write(json.encode(res))
  else
    for _, benchfile in ipairs(res) do
      output_results(benchfile.benches, bpath .. '/' .. benchfile.name,
                     cpath .. '/' .. benchfile.name)
    end
  end
end

------------ Main. -----------------------------------------------

argparse(arg)

local baseline_path, contender_path = arg[1], arg[2]
local base_isdir = isdir(baseline_path)
local cont_isdir = isdir(contender_path)

if base_isdir ~= cont_isdir then
  fatal('Baseline and contender file types should either be file or directory.')
end

if base_isdir then
  output_sets_results(compare_benchmarks_sets(baseline_path, contender_path),
    baseline_path, contender_path
  )
else
  output_results(compare_benchmarks(baseline_path, contender_path),
    baseline_path, contender_path
  )
end
