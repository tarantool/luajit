# JIT Trace Debugging in Tarantool's LuaJIT

Repository analyzed: `tarantool/third_party/luajit` (Tarantool's LuaJIT 2.1 fork,
baseline git HEAD `712e6d85`).

This is the consolidated document for debug-information generation for the traces
collected by the JIT infrastructure. It contains:

* the analysis of every existing mechanism (§1–§4);
* the improvement plan (§5) and file map (§6);
* the implemented precise-debug-info extension, `LUAJIT_USE_PIDEBUG` /
  `jit.pidbg`, including its API, output formats, limitations and tests (§7);
* how to build Tarantool with the extension (§8).

It is meant to be the starting point for any future engineering work that wants to
*add* or *improve* debug information for LuaJIT traces.

---

## 1. Investigation Methodology

The investigation was split across **five parallel research agents**, each owning one
subsystem, all instructed to cite exact `file:line` locations and mine `git log` for the
history/rationale of the current design:

| # | Agent | Subsystem owned |
|---|---|---|
| 1 | GDB JIT / DWARF backend | `src/lj_gdbjit.c`, `src/lj_gdbjit.h`, ELF/DWARF synthesis, `LUAJIT_USE_GDBJIT` |
| 2 | Snapshot & PC/line mapping core | `src/lj_snap.c/.h`, `src/lj_jit.h` (`GCtrace`, `SnapShot`, `SnapEntry`), `src/lj_record.c`, `src/lj_debug.c`, `src/lj_err.c` |
| 3 | Lua-level debug API on traces | `src/lj_debug.c/.h`, `src/lj_api.c`, `src/lib_debug.c`, `src/lj_dispatch.c`, `src/lib_jit.c` (`jit.util.*`) |
| 4 | Tarantool sysprof/memprof/symtab pipeline | `src/lj_symtab.c/.h`, `src/lj_sysprof.c`, `src/lj_memprof.c`, `tools/sysprof/`, `tools/memprof/` |
| 5 | Developer dump tooling & GDB/LLDB extension | `src/jit/dump.lua`, `src/jit/v.lua`, `src/lib_jit.c` (`jit.util.*`), `src/luajit_dbg.py`, `test/tarantool-debugger-tests/` |

Each agent's full report is condensed into §3 below; §2 gives the synthesized architecture
picture; §4 lists concrete gaps; §5 is the actionable plan.

---

## 2. Architecture Overview — Five Independent Debug-Info Layers

LuaJIT does **not** have a single "debug info generator" for traces. Instead there are five
largely independent mechanisms, all deriving from the *same* two low-level primitives
(`GCproto->lineinfo` and trace `SnapShot`s), but packaged very differently for very
different consumers:

```
                        ┌───────────────────────────────────────────┐
                        │   GCproto->lineinfo (bytecode PC → line)   │
                        │   GCtrace->snap[]/snapmap (mcode → PC)     │  <- only two
                        └───────────────────┬─────────────────────┬─┘     real sources
                                             │                     │       of truth
        ┌────────────────────────────────────┴──┐   ┌──────────────┴───────────────────┐
        │ 1. GDB JIT API (lj_gdbjit.c)           │   │ 2. Snapshot-driven runtime        │
        │    opt-in, DWARF/ELF, live gdb only     │   │    PC recovery (lj_snap.c,        │
        │    -DLUAJIT_USE_GDBJIT                  │   │    lj_debug.c, lj_err.c)          │
        └─────────────────────────────────────────┘   │    always on, powers #3 below     │
                                                        └───────────────┬───────────────────┘
        ┌────────────────────────────────────────┐                     │
        │ 3. Lua debug API (lua_getinfo,          │◄────────────────────┘
        │    debug.traceback, jit.util.*)         │
        │    always on, interpreter-accurate only │
        │    after a trace exit                   │
        └──────────────────────────────────────────┘

        ┌────────────────────────────────────────┐   ┌────────────────────────────────────┐
        │ 4. Tarantool symtab/sysprof/memprof     │   │ 5. Developer dump tooling           │
        │    (lj_symtab.c, lj_sysprof.c,          │   │    (jit/dump.lua, jit/v.lua,        │
        │    lj_memprof.c) binary stream, Linux    │   │    luajit_dbg.py GDB/LLDB ext)      │
        │    only, production profiling            │   │    always on / dev-attach only      │
        └────────────────────────────────────────┘   └────────────────────────────────────┘
```

**Key structural fact that shapes everything else:** neither `IRIns` (the SSA IR node,
`src/lj_ir.h:539-563`) nor the compiled machine code carries any per-instruction source
position. The **only** PC-bearing structure attached to a trace is the sparse
`SnapShot`/`SnapEntry` array (`src/lj_jit.h:186-229`), taken only at bytecode boundaries
that follow a side-effecting or guardable operation (the `J->needsnap` protocol,
`src/lj_record.c:2135-2141`). All five layers above are, in the end, thin wrappers around
"the trace's start line" (layers 1, 4, 5) or "whatever the nearest snapshot says"
(layers 2, 3). **There is no fine-grained, per-instruction debug info anywhere in LuaJIT's
trace representation** — this is a deliberate design tradeoff (bounded snapshot count,
mergeable, cheap), not an oversight.

---

## 3. Findings Per Layer

### 3.1 Layer 1 — GDB JIT API (`src/lj_gdbjit.c`)

- Disabled by default; only compiled in when `LUAJIT_USE_GDBJIT` is defined. Tarantool
  exposes this as CMake option `LUAJIT_USE_GDBJIT` (default `OFF`,
  `CMakeLists.txt:269-277`), and gates the source file itself out of the build otherwise
  (`src/CMakeLists.txt:149-153`).
- Registers one synthetic ELF object per trace (`GDBJITobj`, `src/lj_gdbjit.c:336-341`)
  containing `.text` (shadow section pointing at the real mcode), `.eh_frame` (DWARF
  CFI/unwind info), `.debug_info`/`.debug_abbrev`/`.debug_line` (minimal DWARF2), and
  `.symtab`/`.strtab` (`"TRACE_<N>"` symbol name).
- **Only one (address, line) row is ever written to `.debug_line`** — the trace's *start*
  line (`src/lj_gdbjit.c:648-678`). Every address inside the trace's mcode maps to that
  same single source line in GDB. This is explicitly documented in the file's own header
  comment (`src/lj_gdbjit.c:44-48`): *"Currently this is always set to the location where
  the trace has been started."*
- `.eh_frame` unwind info is precise for register-save locations (per-arch, x86/x64/ARM/
  ARM64/PPC/MIPS, `src/lj_gdbjit.c:553-596`) but the CFA-offset transition between the
  parent frame size and the trace's own frame size is explicitly commented
  `/* Only an approximation. */` (`src/lj_gdbjit.c:599`).
- Registered/deregistered via the standard `__jit_debug_register_code`/
  `__jit_debug_descriptor` protocol, called from `trace_save()`
  (`src/lj_trace.c:169`) and `lj_trace_free()`/`lj_trace_flushall()`
  (`src/lj_trace.c:188,300`), protected by a GCC-builtin spinlock
  (`src/lj_gdbjit.c:734-746`).
- **This file is byte-for-byte identical to upstream Mike Pall's LuaJIT** (verified via
  `git diff 064eac00 712e6d85 -- src/lj_gdbjit.c` = empty). Tarantool has never modified
  the GDB-JIT client; its only footprint is the CMake option plumbing and a CI "does it
  still build" flavor (`.github/workflows/exotic-builds-testing.yml`).

### 3.2 Layer 2 — Snapshot-driven PC/line recovery (the core mechanism)

- A **snapshot** (`SnapShot` header + `SnapEntry[]` map, `src/lj_jit.h:186-229`) is a
  compressed description of the full interpreter state (which IR value/constant backs
  each live VM stack slot, plus the frame-link chain and the bytecode PC to resume at) as
  it would exist if execution fell back to the interpreter at that point.
- Snapshots are **not** taken per-IR-instruction or even per-bytecode. They are taken:
  (a) once at trace start (`src/lj_record.c:2732`), (b) once per loop-back edge
  (`src/lj_record.c:306`), and (c) lazily via the `J->needsnap` flag immediately before any
  side-effecting/guardable operation (`src/lj_record.c:2135-2141`). Adjacent snapshots at
  the same IR position are merged (`src/lj_snap.c:186-197`).
- On trace exit (guard failure, loop exit, or unwind-driven error), `lj_snap_restore()`
  (`src/lj_snap.c:938-1024`) restores the bytecode PC from the chosen snapshot and
  deliberately advances it to `pc+1` (except for returns/tailcalls) *specifically so a
  subsequent error message reports the correct line* (`src/lj_snap.c:956-961`).
- For **errors raised directly by a C helper called from machine code** (no preceding
  guard), LuaJIT uses a custom DWARF personality routine (`err_unwind_jit()`,
  `src/lj_err.c:497-528`) that maps the throwing call's return address back to a snapshot
  via `lj_trace_unwind()`'s binary search over `SnapShot.mcofs`
  (`src/lj_trace.c:980-1011`), then redirects control to that snapshot's exit stub before
  the error is ever visible to Lua — i.e. **every user-visible error is guaranteed to be
  reported with interpreter-accurate (snapshot-granularity) location info**, at the cost
  of an unwind roundtrip.
- Bytecode PC → source line is a flat per-prototype lookup, `lj_debug_line()`
  (`src/lj_debug.c:120-135`), against `GCproto->lineinfo` — a compact delta table
  (1/2/4-byte width depending on function size) added to `pt->firstline`.
- **Confirmed empty**: `IRIns` (`src/lj_ir.h:539-563`) has zero bits reserved for
  position/line info — a hard 64-bit union of two operand refs, type, opcode, and
  register/spill fields. There is no way to ask "what line does *this specific* IR
  instruction correspond to" — only "what does the nearest snapshot say".

### 3.3 Layer 3 — Lua-level debug API on traced code

- `debug_framepc()` (`src/lj_debug.c:53-115`) is the single chokepoint behind
  `lua_getinfo`, `debug.getinfo`, `debug.traceback`. While native trace code is *actually
  running*, the interpreter's own PC register (`cframe_pc`) is stale — it still points at
  the trace's entry bytecode (loop/function header), because nothing inside compiled code
  updates it. It only becomes accurate again after a snapshot-restore-driven trace exit.
- In practice this is rarely observable: none of `debug.getinfo`/`debug.traceback`/
  `debug.sethook` are JIT-recordable (no `LJLIB_REC`, `src/lib_debug.c:110,323,385`); the
  recorder either stitches them through the interpreter or aborts recording outright
  (`recff_nyi`, `src/lj_ffrecord.c:160-186`), so by the time they run, state has already
  been resynced.
- **Debug hooks (line/call/count/return) cannot fire from inside compiled trace code at
  all** — hooks are pure bytecode-dispatch-table rewrites (`lj_dispatch_update()`,
  `src/lj_dispatch.c:104-205`) and once control jumps into native mcode
  (`BC_JLOOP`/`BC_JFUNC*`), the dispatch table is never consulted again until the trace
  exits. The only hook opportunity is a single check at the `JLOOP` dispatch slot when
  *entering* the trace — after that, an entire hot loop can execute with zero hook
  callbacks. The only escape hatch is the disabled-by-default
  `LUAJIT_ENABLE_CHECKHOOK` build option (`src/lj_record.c:2744-2764`), which emits a
  per-iteration IR guard checking `hookmask`, explicitly meant only for *asynchronous*
  interruption (e.g. Ctrl-C), not line-stepping.
- `jit.util.traceinfo(tr)` (`src/lib_jit.c:292-309`) exposes only coarse trace metadata
  (`nins`, `nk`, `link`, `nexit`, `linktype`) — **no start line, no mcode address**. Those
  require the lower-level `jit.util.tracemc`/`tracesnap`/`traceir`/`tracek` functions
  (`src/lib_jit.c:312-411`), which give IR/constant/snapshot/mcode access but still no
  ready-made "IR ref → source line" mapping.
- Multiple historical bugs (`f50075a9`, `fdbef777`/`1d75cd4d`, the 2025
  `e69b13fd`/`e3fa3c48` series) show this exact code path
  (`debug_framepc`'s JLOOP/return-PC reconstruction hack, `src/lj_debug.c:103-113`) has
  been a **recurring source of debug-info correctness bugs** specifically tied to trace
  exits (stack-overflow-from-stitched-trace, out-of-range PC underflow at `NO_BCPOS`,
  partial snapshot restore). The most recent fix is from 2025.

### 3.4 Layer 4 — Tarantool sysprof/memprof/symtab pipeline

- Tarantool-specific addition (ported from LuaVela), gated by `LJ_HASSYSPROF`/
  `LJ_HASMEMPROF` (Linux-only for sysprof; `src/lj_arch.h:656-672`), compiled in by
  default, opt-out via CMake (`LUAJIT_DISABLE_{SYSPROF,MEMPROF}`).
- Own binary streaming format (`'ljs'` symtab + `'ljp'`/`'ljm'` event streams,
  `src/lj_symtab.h:19-61`) written via a `lj_wbuf` writer callback — designed for
  **low, bounded, signal-handler-safe overhead**, unlike GDB JIT.
- Captures, per trace, exactly: `traceno`, the associated `GCproto*` pointer, and the
  **trace-start line** (`lj_symtab_dump_trace`, `src/lj_symtab.c:33-54`) — i.e. the same
  "start-line-only" granularity as GDB JIT, by a completely independent code path. No
  mcode address range is recorded in current code (an earlier design did stream
  `trace->mcode`; it was intentionally removed in commit `0243fb72` once traces were
  identified purely by stable `traceno`).
- Lifecycle: full symtab snapshot at `sysprof.start()`/`memprof.start()`, then incremental
  single-symbol appends whenever a new `GCproto` is compiled/loaded or a new `GCtrace` is
  finalized (`lj_sysprof_add_proto/add_trace`, `lj_memprof_add_proto/add_trace`, hooked
  from `lj_parse.c`, `lj_bcread.c`, `lj_trace.c:176,180`).
- Sysprof identifies the *currently executing* trace via `g->vmstate` directly (no PC
  sampling/backtracing needed) — `stream_trace()` (`src/lj_sysprof.c:237-250`).
- Commit `ec0d1c0c` ("sysprof: disable runtime host symtab updates") is the most
  significant correctness/safety fix in this area: ELF-resolving newly-`dlopen`'d shared
  libraries from inside a SIGPROF handler is not async-signal-safe, so this capability was
  removed from sysprof's hot path — **any `.so`/FFI module loaded after `sysprof.start()`
  will show up as unresolved in sysprof reports**, a documented, accepted limitation.
  Memprof keeps this capability since its hooks run in ordinary (non-signal) allocator
  context.
- Human-readable reconstruction happens entirely offline in Lua tooling
  (`tools/utils/symtab.lua`, `tools/sysprof/parse.lua`, `tools/memprof/{parse,humanize}.lua`),
  which demangle `(traceno, addr, line)` triples into `"chunk:line"` strings and
  `"TRACE [n] started at chunk:line"` labels, ultimately producing folded-stack /
  heap-delta reports.

### 3.5 Layer 5 — Developer dump tooling & GDB/LLDB extension

- `-jdump`/`-jv` (`src/jit/dump.lua`, `src/jit/v.lua`) never re-read the original `.lua`
  source file — LuaJIT doesn't retain source text at runtime. All "source annotation" is
  really a `chunk:line` tag (`fmtfunc()` → `jit.util.funcinfo(func,pc).loc`, itself built
  by `lj_debug_pushloc()`/`lj_debug_line()` in C, `src/lj_debug.c:120,380-405`). `-jdump`'s
  bytecode listing comes from `jit.bc.line()` (pure metadata disassembly, no source text).
- `jit.util.*` (`src/lib_jit.c`) is the full reflection surface: `funcinfo`, `funcbc`,
  `funck`, `funcuvname` (prototype-level), and `traceinfo`, `traceir`, `tracek`,
  `tracesnap`, `tracemc`, `traceexitstub`, `ircalladdr` (trace-level) — together these
  expose essentially the entire `GCtrace`/`IRIns`/`SnapShot` structure to Lua, and are the
  foundation both `dump.lua` and any third-party tooling would build on.
- **`src/luajit_dbg.py`** is Tarantool's own GDB/LLDB Python extension (introduced
  2026-05-14, `5db8c217`) for live/core-dump introspection. Its trace/IR-specific commands
  — `lj-ir`, `lj-jslots`, `lj-trace` — were added in commit `01a0f2f7`
  ("dbg: introduce lj-ir, lj-jslots, lj-trace dumpers") and let a developer dump an entire
  compiled trace's IR (with register/spill and snapshot overlays via `/r`/`/s` flags)
  directly from a stopped debugger, without needing the JIT to still be live or
  `-jdump` to have been enabled ahead of time. This is validated by a dedicated test suite
  (`test/tarantool-debugger-tests/debug-extension-tests.py`, ~15 trace/IR-specific test
  classes) run in CI against both GDB and LLDB, on ARM64/x86_64 × GC64 on/off.

---

## 4. Gaps and Limitations (synthesized)

| # | Gap | Impact | Where it lives |
|---|---|---|---|
| G1 | Every trace-level debug-info mechanism (GDB JIT, symtab) records **only the trace's start line**, never a range or per-block mapping. | `list`/`info line` in gdb, and sysprof "started at chunk:line" labels, are accurate only for where the trace *began*, not where a sample/breakpoint address actually falls within a (possibly large, inlined) trace. | `lj_gdbjit.c:44-48`, `lj_symtab.c:33-54` |
| G2 | `IRIns` carries **zero** position metadata; there's no per-IR-instruction line map. | Fine-grained "which source line produced this specific IR op" is impossible without re-deriving it from the sequence of preceding needsnap-triggered snapshots — awkward and only approximately possible even manually. | `lj_ir.h:539-563` |
| G3 | Debug hooks cannot fire during trace execution (only once, at trace entry). | Line-stepping through hot/JIT-compiled loops is effectively impossible without `jit.off()`; `LUAJIT_ENABLE_CHECKHOOK` is disabled by default and is not a stepping mechanism anyway. | `lj_dispatch.c:104-205`, `lj_record.c:2744-2764` |
| G4 | `cframe_pc`/`currentline` is stale while native trace code is *actually* running (only accurate at/after a trace exit). | Any hypothetical external sampler that reads `cframe_pc` asynchronously (rather than via a proper unwind) would get a misleading line. Currently nothing does this unsafely, but it's a latent trap for future code. | `lj_debug.c:53-115`, `lj_snap.c:938-961` |
| G5 | `jit.util.traceinfo` omits `startline`/mcode address entirely ("Add them only when needed" comment). | Building custom Lua-level trace/debug tooling requires falling through to lower-level `tracemc`/`tracesnap`/`funcinfo` calls and manual reconstruction — no single convenient call. | `lib_jit.c:292-309` |
| G6 | `debug_framepc()`'s JLOOP/return-PC reconstruction hack (pointer arithmetic on `offsetof(GCtrace, startins)`) is fragile scaffolding. | Repeated real bugs (2011, 2023, 2025) each time a new trace-exit corner case (stitched trace + stack overflow, PC underflow, partial snapshot restore) wasn't anticipated by this hack. | `lj_debug.c:103-113` |
| G7 | Sysprof cannot resolve C symbols for shared libraries/FFI modules loaded **after** `sysprof.start()` (removed for signal-handler safety in `ec0d1c0c`). | Reports show `CFUNC 0x...` for any lazily-loaded native code path, degrading readability for long-running/production processes that load modules dynamically. | `lj_sysprof.c` (`stream_host`), commit `ec0d1c0c` |
| G8 | GDB JIT `.eh_frame` CFA-offset transition between parent-frame size and trace-frame size is only a 1-byte approximation. | Extremely early-in-trace unwinding (`info frame` right at trace entry) can be imprecise; unlikely to matter in practice but is an explicitly acknowledged inaccuracy. | `lj_gdbjit.c:599` |
| G9 | No mechanism ties an **exit number** (snapshot index) back to a human-friendly location from Lua without manual work (`tracesnap` returns IR refs, not PCs/lines). | Post-mortem "which of N side exits fired, and where" analysis from pure Lua tooling requires combining `tracesnap`'s IR ref with the trace's `startpc` and further inference — no direct `tracesnap → line` helper exists. | `lib_jit.c:355-374` |

---

## 5. Plan: Improving Debug-Information Generation for Traces

This plan is ordered by increasing implementation cost/risk. Each item names the primary
files to touch and the layer(s) it improves (see §2/§4).

### Phase 0 — Documentation & low-risk wins (no behavior change)
1. **Document the "start-line-only" limitation prominently** in `jit.util.traceinfo`'s
   doc/comment and in Tarantool's own docs, so tooling authors don't assume finer
   granularity exists (addresses confusion behind G1/G5).
2. **Expose `startline`/`startaddr`/mcode range on `jit.util.traceinfo`** (`lib_jit.c:292-309`)
   — trivial addition (`GCtrace->startpt/startpc/mcode/szmcode` are already resident),
   closing G5 without any format/ABI change. Low risk, immediately useful for any
   Lua-level tooling (including Tarantool's own `tools/sysprof`, `tools/memprof`).

### Phase 1 — Strengthen the existing snapshot-based ground truth (Layer 2/3)
3. **Add a `jit.util.tracepc(tr, exitno)` (or extend `tracesnap`) helper** that decodes a
   snapshot's frame-link PC entry (`snap_pc()`, `lj_jit.h:220-229`) directly to a
   `(proto, bcpos, line)` triple, closing G9. This reuses existing C-side decode logic
   (`lj_snap_restore`'s PC extraction, `lj_snap.c:938-961`) exposed as a pure query.
4. **Harden `debug_framepc()`'s JLOOP-hack** (G6) by adding an explicit, named predicate
   (e.g. `pc_is_trace_trampoline()`) instead of the current implicit
   `pos > pt->sizebc` + `bc_isret()` combination, plus a regression-test matrix covering
   every trace-exit corner case seen in the historical bug list (§3.3) — stitched-trace
   stack overflow, first-bytecode underflow, partial snapshot restore, down-recursive
   traces. This is a refactor-for-robustness, not a new feature, aimed at preventing a
   fourth recurrence of the same class of bug.

### Phase 2 — Per-range (not just per-start) line info for interactive debugging (Layer 1)
5. **Extend `lj_gdbjit.c`'s `.debug_line` program to emit one row per snapshot**, not just
   one row for the whole trace (G1/G8). Since every snapshot already carries a bytecode PC
   (`snap_pc`) and an mcode offset (`SnapShot.mcofs`, filled at asm time,
   `lj_asm.c:1023-1048`), the line-table generator (`gdbjit_debugline()`,
   `lj_gdbjit.c:648-678`) can walk `T->snap[]` and emit
   `DW_LNS_advance_pc <snap[i].mcofs-prev> ; DW_LNS_advance_line <delta> ; DW_LNS_copy`
   per snapshot instead of a single static row. This directly improves `gdb`'s `list`/
   `disas /s` output for anyone building with `LUAJIT_USE_GDBJIT`, at the cost of a larger
   `.debug_line` payload (still bounded by `nsnap`, capped at `JIT_P_maxsnap`, default
   500). Since this file is currently untouched from upstream (§3.1), this would be a
   genuine, well-scoped Tarantool-specific enhancement — consider upstreaming it too.
6. **Fix the CFA-offset approximation** in the FDE (G8) by emitting the frame-size
   transition at the *exact* first-instruction boundary using a real machine-code offset
   (available at `lj_gdbjit_addtrace` time via `T->szmcode`/known prologue size) instead of
   the current `DW_CFA_advance_loc|1` placeholder (`lj_gdbjit.c:599`).

### Phase 3 — Production profiling completeness (Layer 4)
7. **Restore late-loaded C-symbol resolution for sysprof without sacrificing
   signal-safety** (G7): move the ELF/`dlopen`-resolution work out of the SIGPROF handler
   by having the handler enqueue a lock-free "new library seen" notification (e.g. a
   generation counter compared against `_dl_phdr_removals`/`dlpi_adds`) and perform the
   actual `lj_symtab_dump_newc()` work from a safe context (e.g. the next
   `lj_sysprof_add_trace`/`add_proto` call, or a dedicated non-signal maintenance hook),
   mirroring what memprof already does safely. This closes a real, documented production
   limitation (commit `ec0d1c0c`) without reintroducing the original crash risk.
8. **Optionally record an mcode address (or address-range) alongside the trace's start
   line in the symtab** (reversing part of commit `0243fb72`, but keyed by `(traceno,
   generation)` rather than raw address to avoid the original collision problem) — would
   let `tools/sysprof` attribute *interior* trace samples to more than just "the trace
   started here", complementing item 3/5.

### Phase 4 — Debuggability of hot loops (Layer 3)
9. **Investigate a bounded-cost "checkpoint" hook mode**: rather than the current
   all-or-nothing `LUAJIT_ENABLE_CHECKHOOK` (per-iteration `hookmask` guard, disabled by
   default because "quite expensive"), evaluate a cheaper sampling-based variant (e.g. tied
   to the existing `lj_profile_timer` infrastructure used by sysprof) that could give
   *approximate* line-hook-like behavior for hot traces without the full per-iteration
   guard cost. This is exploratory (G3/G4) and should start as a design spike, not a
   direct implementation, given the deliberate historical decision to keep this off by
   default.

### Suggested sequencing
Phases 0–1 are pure additive/refactor work with no format or ABI impact and should be done
first. Phase 2 only matters for the opt-in, non-production `LUAJIT_USE_GDBJIT` path, so it
is low-risk to prototype independently. Phase 3 addresses a real, currently-documented
production gap in a widely-used (default-on) subsystem and should be prioritized ahead of
Phase 4, which is the highest-risk/most-exploratory item (touches the hot recording path
and the historically-fragile hook/trace interaction, cf. `ee1daeee`/`ac306b3f` "Avoid
recording interference due to invocation of VM hooks").

---

## 6. Appendix — File Map

| File | Role |
|---|---|
| `src/lj_ir.h` | `IRIns` definition — confirmed to carry no debug/position info |
| `src/lj_jit.h` | `GCtrace`, `SnapShot`, `SnapEntry`, `jit_State` layouts |
| `src/lj_record.c` | Bytecode recording, `J->needsnap` protocol, snapshot insertion points |
| `src/lj_snap.c` / `lj_snap.h` | Snapshot construction, `lj_snap_restore` (trace exit → PC) |
| `src/lj_asm.c` | Fills in `SnapShot.mcofs` during code generation |
| `src/lj_debug.c` / `lj_debug.h` | `lj_debug_line`, `debug_framepc`, `lj_debug_pushloc` — the bytecode-PC-to-line core, and the JIT-exit-aware special cases |
| `src/lj_err.c` | JIT-aware error unwinding (`err_unwind_jit`), `lj_err_run`'s `jit_base` handling |
| `src/lj_api.c`, `src/lib_debug.c` | `lua_getinfo`, `debug.*` library |
| `src/lj_dispatch.c` | Hook dispatch-table rewriting; why hooks can't fire mid-trace |
| `src/lj_gdbjit.c` / `lj_gdbjit.h` | GDB JIT API client (opt-in, unmodified from upstream) |
| `src/lj_symtab.c` / `lj_symtab.h` | Tarantool's binary symbol-table format (`'ljs'`) |
| `src/lj_sysprof.c` / `lj_memprof.c` | Tarantool's sampling/allocation profilers, consumers of `lj_symtab` |
| `src/lib_jit.c` | `jit.util.*` reflection API |
| `src/jit/dump.lua`, `src/jit/v.lua` | `-jdump`/`-jv` developer tooling |
| `src/luajit_dbg.py` | Tarantool's GDB/LLDB extension (`lj-trace`, `lj-ir`, `lj-jslots`, etc.) |
| `tools/sysprof/`, `tools/memprof/`, `tools/utils/symtab.lua` | Offline report generators for layer 4 |
| `test/tarantool-debugger-tests/` | Tests for `luajit_dbg.py` trace/IR commands |

---

## 7. Implemented extension: `LUAJIT_USE_PIDEBUG` (`jit.pidbg`)

Item 5 of Phase 2 above (a per-snapshot `.debug_line`) is implemented as
a standalone plugin, `src/lj_pidbg.c`, without touching `lj_gdbjit.c`.
The other plan items remain open.

### Build

```sh
cmake -DLUAJIT_USE_PIDEBUG=ON ...
```

The option is off by default, requires the JIT and is mutually exclusive
with `LUAJIT_USE_GDBJIT` (both define the GDB JIT descriptor). When the
option is off, every hook compiles to a no-op.

### Lua API

```lua
local pidbg = require("jit.pidbg")
pidbg.start(mode, sidecar_path, jitdump_path)  -- mode: "l" | "b"
pidbg.stop()
pidbg.active()
pidbg.trace(tr)  -- array of { mcoff=, bcpos=, line=, file= } or nil
```

`mode` selects the checkpoint granularity: `"l"` takes a checkpoint
whenever the source line changes, `"b"` at every bytecode boundary. The
two optional paths enable the file outputs described below.

### Mechanism

The plugin reuses the existing line profiler machinery: setting
`J->prof_mode` makes `rec_profile_ins()` emit an `IR_PROF` guard and take
a full snapshot at every tracked point. The `HOOK_PROFILE` bit is left
clear, so the guards never cause a trace exit. The plugin remembers the
origin `(GCproto *, BCPos)` of each snapshot while recording and, when the
trace is saved, joins it with `SnapShot.mcofs` and `T->mcode` to resolve
source lines. The resolved table is then turned into:

* an in-memory ELF object registered with the GDB JIT API, carrying a
  multi-row `.debug_line`, `.eh_frame`, `.debug_info` and the `TRACE_<n>`
  symbol;
* an optional text sidecar with one line per checkpoint;
* an optional jitdump file with `JIT_CODE_DEBUG_INFO`, `JIT_CODE_LOAD` and
  `JIT_CODE_UNWINDING_INFO` records.

### Using the debugger

```sh
luajit -e 'local p=require("jit.pidbg"); p.start("l")' app.lua &
pstack $!        # or: gdb -batch -p $! -ex bt
```

The backtrace shows `TRACE_<n> () at app.lua:<line>`, where `<line>` is
the exact source line of the interrupted instruction, not the line where
the trace started. Outer C frames beyond the trace are limited by the
hand-written VM, exactly as with the upstream `LUAJIT_USE_GDBJIT` client.

### Output formats

Sidecar (TAB-separated, file name last):

```
trace<TAB>traceno<TAB>mcode_addr<TAB>szmcode
span<TAB>traceno<TAB>mcoff<TAB>bcpos<TAB>line<TAB>file
end<TAB>traceno
```

jitdump: the Linux perf format (little-endian), with one debug-info,
load and unwinding-info record per trace.

### Limitations

* The profiler is process-wide: `start()` sets `J->prof_mode` and flushes
  all traces. It should not run together with the sampling profiler
  (`jit.p`).
* The bytecode mode takes a snapshot per bytecode, so traces that exceed
  the snapshot limit (`maxsnap`, 500 by default) abort with
  `LJ_TRERR_SNAPOV` and get no debug info. The line mode is the practical
  default.
* jitdump records are append-only; a flushed trace has no unload record,
  so a bounded profiling window is expected.
* The jitdump `JIT_CODE_UNWINDING_INFO` carries the `.eh_frame` bytes with
  a minimal (all-omit) `eh_frame_hdr`; the GDB JIT path is the unwinding
  path validated by the tests.

### Testing

```
test/tarantool-tests/lj-pidbg-jitdump.test.lua     # sidecar + jitdump
test/tarantool-tests/lj-pidbg-stability.test.lua   # churn/flush stability
test/tarantool-tests/lj-pidbg-pstack.test.lua      # gdb/pstack integration
```

The state owned by the feature (including the thread-local checkpoint
buffer) is released both by `jit.pidbg.stop()` and, as a safety net, on VM
state teardown from `lj_trace_freestate()`. This keeps `LUA_USE_ASSERT`
builds (for example Tarantool Debug) from aborting in `close_state` with a
memory leak when the feature is used or when `stop()` was forgotten.

---

## 8. Building Tarantool with the extension

The Tarantool superproject exposes the option and forwards it to the
bundled LuaJIT:

* `CMakeLists.txt`:
  `option(LUAJIT_USE_PIDEBUG "Build LuaJIT with precise JIT trace debug info." OFF)`
* `cmake/luajit.cmake`: forwards the value as a forced cache variable to
  `third_party/luajit` (the same pattern as `LUAJIT_ENABLE_GC64`) and fails
  the configuration early if the bundled LuaJIT does not provide
  `src/lj_pidbg.c`.

Build:

```sh
cmake -DLUAJIT_USE_PIDEBUG=ON ... -B build
cmake --build build --target tarantool
```

The option defaults to `OFF`, so a normal build is unaffected. It requires
the JIT and is mutually exclusive with `LUAJIT_USE_GDBJIT`.

Smoke test of the built binary:

```lua
-- check.lua
local pidbg = require('jit.pidbg')
assert(pidbg.active() == false)
pidbg.start('l')
local function work(n)
  local s = 0
  for i = 1, n do s = s + i end
  return s
end
local r = 0
for i = 1, 200 do r = r + work(1000) end
pidbg.stop()
```

```sh
build/src/tarantool check.lua   # no leak assertion, prints nothing
```

For debugger validation, attach while the process executes a compiled
trace (see §7): `pstack <pid>` or `gdb -batch -p <pid> -ex bt` shows
`TRACE_<n> () at <file>:<line>`.


