/*
** Implementation of memory profiler.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#include "lj_wbuf.h"
#define lj_memprof_c
#define LUA_CORE

#include <dlfcn.h>
#include <errno.h>

#include "lauxlib.h"
#include "lj_arch.h"
#include "lj_memprof.h"
#include "lua.h"

#if LJ_HASMEMPROF

#include "lj_debug.h"
#include "lj_frame.h"
#include "lj_obj.h"

/* --------------------------------- Symtab --------------------------------- */

static const unsigned char ljs_header[] = {'l', 'j', 's', LJS_CURRENT_VERSION,
                                           0x0, 0x0, 0x0};

static void dump_symtab(struct lj_wbuf *out, const struct global_State *g) {
  const GCRef *iter = &g->gc.root;
  const GCobj *o;
  const size_t ljs_header_len = sizeof(ljs_header) / sizeof(ljs_header[0]);

  /* Write prologue. */
  lj_wbuf_addn(out, ljs_header, ljs_header_len);

  while ((o = gcref(*iter)) != NULL) {
    switch (o->gch.gct) {
      case (~LJ_TPROTO): {
        const GCproto *pt = gco2pt(o);
        lj_wbuf_addbyte(out, SYMTAB_LFUNC);
        lj_wbuf_addu64(out, (uintptr_t)pt);
        lj_wbuf_addstring(out, proto_chunknamestr(pt));
        lj_wbuf_addu64(out, (uint64_t)pt->firstline);
        break;
      }
      default:
        break;
    }
    iter = &o->gch.nextgc;
  }

  lj_wbuf_addbyte(out, SYMTAB_FINAL);
}

/* -------------------------------- Csymtab --------------------------------- */
#define SOTAB_MIN_STACK 3

void create_csymtab(lua_State *L, int *ref) {
  if (!lua_checkstack(L, SOTAB_MIN_STACK)) {
    luaL_error(L, "Not enough stack space to dump C symbol table!\n");
  }

  lua_newtable(L);
  *ref = luaL_ref(L, LUA_REGISTRYINDEX);
}

void free_csymtab(lua_State *L, const int ref) {
  luaL_unref(L, LUA_REGISTRYINDEX, ref);
}

void append_csymtab(lua_State *L, int *ref, const void *ptr) {
  lua_checkstack(L, SOTAB_MIN_STACK);
  lua_rawgeti(L, LUA_REGISTRYINDEX, *ref); /* place csymtab from registry
                                             to stack */
  luaL_checktype(L, -1, LUA_TTABLE);

  lua_pushinteger(L, (uint64_t)ptr);
  lua_pushinteger(L, 0); /* function attributes are going to be there later */
  lua_settable(L, -3);
  lua_pop(L, 1);
}

void resolve_csymtab(lua_State *L, int *ref) {
  lua_rawgeti(L, LUA_REGISTRYINDEX, *ref);
  luaL_checktype(L, -1, LUA_TTABLE);

  lua_pushnil(L);  /* first key */
  while (lua_next(L, -2) != 0) {
    lua_pop(L, 1); 

    uint64_t ptr = lua_tointeger(L, -1);
    printf("Key: %p", (void*)ptr);
    fflush(stdout);


    Dl_info c_sym = {};
    dladdr((void *)ptr, &c_sym);

    lua_newtable(L);

    lua_pushstring(L, c_sym.dli_fname); // pushstring is NULL-safe
    lua_setfield(L, -2, "file");
    lua_pushstring(L, c_sym.dli_sname);
    lua_setfield(L, -2, "symbol");

    lua_settable(L, -3);
    lua_pushinteger(L, ptr);
  }
  lua_pop(L, 1);
}

void write_csymtab(lua_State *L, int *ref, struct lj_wbuf *out) {
  FILE* log = fopen("/home/maxim/Programming/memprof-demangling/log.txt", "w");
  lua_rawgeti(L, LUA_REGISTRYINDEX, *ref);
  luaL_checktype(L, -1, LUA_TTABLE);

  lua_pushnil(L); /* first key */
  while (lua_next(L, -2) != 0) {
    lj_wbuf_addbyte(out, CSYMTAB_CFUNC);
    lj_wbuf_addu64(out, lua_tointeger(L, -2));

    fprintf(log, "Pointer %p ", (void*)lua_tointeger(L, -2));

    lua_getfield(L, -1, "file");
    if (lua_isstring(L, -1)) {
      const char *file = lua_tostring(L, -1);
      fprintf(log, "File: %s ", file);
      lj_wbuf_addstring(out, file);
    }
    lua_pop(L, 1);
    
    lua_getfield(L, -1, "symbol");
    if (lua_isstring(L, -1)) {
      const char *symbol = lua_tostring(L, -1);
      fprintf(log, "Symbol: %s\n", symbol);
      fflush(stdout);
      lj_wbuf_addstring(out, symbol);
    }
    lua_pop(L, 2);

  }
  lua_pop(L, 1);
  fclose(log);
}

/* ---------------------------- Memory profiler ----------------------------- */

enum memprof_state {
  /* Memory profiler is not running. */
  MPS_IDLE,
  /* Memory profiler is running. */
  MPS_PROFILE,
  /*
  ** Stopped in case of stopped stream.
  ** Saved errno is returned to user at lj_memprof_stop.
  */
  MPS_HALT
};

struct alloc {
  lua_Alloc allocf; /* Allocating function. */
  void *state;      /* Opaque allocator's state. */
};

struct memprof {
  global_State *g;               /* Profiled VM. */
  enum memprof_state state;      /* Internal state. */
  struct lj_wbuf out;            /* Output accumulator. */
  struct alloc orig_alloc;       /* Original allocator. */
  struct lj_memprof_options opt; /* Profiling options. */
  int saved_errno;               /* Saved errno when profiler deinstrumented. */
  int csymtab;                   /* Lua reference to symbol table for C functions. */
};

static struct memprof memprof = {0};

const unsigned char ljm_header[] = {'l', 'j', 'm', LJM_CURRENT_FORMAT_VERSION,
                                    0x0, 0x0, 0x0};

static void memprof_write_lfunc(struct lj_wbuf *out, uint8_t aevent, GCfunc *fn,
                                struct lua_State *L, cTValue *nextframe) {
  const BCLine line = lj_debug_frameline(L, fn, nextframe);
  lj_wbuf_addbyte(out, aevent | ASOURCE_LFUNC);
  lj_wbuf_addu64(out, (uintptr_t)funcproto(fn));
  /*
  ** Line is >= 0 if we are inside a Lua function.
  ** There are cases when the memory profiler attempts
  ** to attribute allocations triggered by JIT engine recording
  ** phase with a Lua function to be recorded. At this case
  ** lj_debug_frameline() may return BC_NOPOS (i.e. a negative value).
  ** Equals to zero when LuaJIT is built with the
  ** -DLUAJIT_DISABLE_DEBUGINFO flag.
  */
  lj_wbuf_addu64(out, line >= 0 ? (uint64_t)line : 0);
}

static void memprof_write_cfunc(struct lj_wbuf *out, uint8_t aevent,
                                const GCfunc *fn, lua_State* L, int* csymtab) {
  //append_csymtab(L, csymtab, fn->c.f);
  lj_wbuf_addbyte(out, aevent | ASOURCE_CFUNC);
  lj_wbuf_addu64(out, (uintptr_t)fn->c.f);
}

static void memprof_write_ffunc(struct lj_wbuf *out, uint8_t aevent, GCfunc *fn,
                                struct lua_State *L, cTValue *frame, int* csymtab) {
  cTValue *pframe = frame_prev(frame);
  GCfunc *pfn = frame_func(pframe);

  /*
  ** XXX: If a fast function is called by a Lua function, report the
  ** Lua function for more meaningful output. Otherwise report the fast
  ** function as a C function.
  */
  if (pfn != NULL && isluafunc(pfn))
    memprof_write_lfunc(out, aevent, pfn, L, frame);
  else
    memprof_write_cfunc(out, aevent, fn, L, csymtab);
}

static void memprof_write_func(struct memprof *mp, uint8_t aevent) {
  struct lj_wbuf *out = &mp->out;
  lua_State *L = gco2th(gcref(mp->g->mem_L));
  cTValue *frame = L->base - 1;
  GCfunc *fn = frame_func(frame);
  int* csymtab = &mp->csymtab;

  if (isluafunc(fn))
    memprof_write_lfunc(out, aevent, fn, L, NULL);
  else if (isffunc(fn))
    memprof_write_ffunc(out, aevent, fn, L, frame, csymtab);
  else if (iscfunc(fn))
    memprof_write_cfunc(out, aevent, fn, L, csymtab);
  else
    lua_assert(0);
}

static void memprof_write_hvmstate(struct memprof *mp, uint8_t aevent) {
  lj_wbuf_addbyte(&mp->out, aevent | ASOURCE_INT);
}

typedef void (*memprof_writer)(struct memprof *mp, uint8_t aevent);

static const memprof_writer memprof_writers[] = {
    memprof_write_hvmstate, /* LJ_VMST_INTERP */
    memprof_write_func,     /* LJ_VMST_LFUNC */
    memprof_write_func,     /* LJ_VMST_FFUNC */
    memprof_write_func,     /* LJ_VMST_CFUNC */
    memprof_write_hvmstate, /* LJ_VMST_GC */
    memprof_write_hvmstate, /* LJ_VMST_EXIT */
    memprof_write_hvmstate, /* LJ_VMST_RECORD */
    memprof_write_hvmstate, /* LJ_VMST_OPT */
    memprof_write_hvmstate, /* LJ_VMST_ASM */
    /*
    ** XXX: In ideal world, we should report allocations from traces as well.
    ** But since traces must follow the semantics of the original code,
    ** behaviour of Lua and JITted code must match 1:1 in terms of allocations,
    ** which makes using memprof with enabled JIT virtually redundant.
    ** Hence use the stub below.
    */
    memprof_write_hvmstate /* LJ_VMST_TRACE */
};

static void memprof_write_caller(struct memprof *mp, uint8_t aevent) {
  const global_State *g = mp->g;
  const uint32_t _vmstate = (uint32_t)~g->vmstate;
  const uint32_t vmstate = _vmstate < LJ_VMST_TRACE ? _vmstate : LJ_VMST_TRACE;

  memprof_writers[vmstate](mp, aevent);
}

static void *memprof_allocf(void *ud, void *ptr, size_t osize, size_t nsize) {
  struct memprof *mp = &memprof;
  const struct alloc *oalloc = &mp->orig_alloc;
  struct lj_wbuf *out = &mp->out;
  void *nptr;

  lua_assert(MPS_PROFILE == mp->state);
  lua_assert(oalloc->allocf != memprof_allocf);
  lua_assert(oalloc->allocf != NULL);
  lua_assert(ud == oalloc->state);

  nptr = oalloc->allocf(ud, ptr, osize, nsize);

  if (nsize == 0) {
    memprof_write_caller(mp, AEVENT_FREE);
    lj_wbuf_addu64(out, (uintptr_t)ptr);
    lj_wbuf_addu64(out, (uint64_t)osize);
  } else if (ptr == NULL) {
    memprof_write_caller(mp, AEVENT_ALLOC);
    lj_wbuf_addu64(out, (uintptr_t)nptr);
    lj_wbuf_addu64(out, (uint64_t)nsize);
  } else {
    memprof_write_caller(mp, AEVENT_REALLOC);
    lj_wbuf_addu64(out, (uintptr_t)ptr);
    lj_wbuf_addu64(out, (uint64_t)osize);
    lj_wbuf_addu64(out, (uintptr_t)nptr);
    lj_wbuf_addu64(out, (uint64_t)nsize);
  }

  /* Deinstrument memprof if required. */
  if (LJ_UNLIKELY(lj_wbuf_test_flag(out, STREAM_STOP)))
    lj_memprof_stop(mainthread(mp->g));

  return nptr;
}

int lj_memprof_start(struct lua_State *L,
                     const struct lj_memprof_options *opt) {
  struct memprof *mp = &memprof;
  struct lj_memprof_options *mp_opt = &mp->opt;
  struct alloc *oalloc = &mp->orig_alloc;
  const size_t ljm_header_len = sizeof(ljm_header) / sizeof(ljm_header[0]);

  lua_assert(opt->writer != NULL);
  lua_assert(opt->on_stop != NULL);
  lua_assert(opt->buf != NULL);
  lua_assert(opt->len != 0);

  if (mp->state != MPS_IDLE) {
    /* Clean up resourses. Ignore possible errors. */
    opt->on_stop(opt->ctx, opt->buf);
    return PROFILE_ERRRUN;
  }

  /* Discard possible old errno. */
  mp->saved_errno = 0;

  /* Init options. */
  memcpy(mp_opt, opt, sizeof(*opt));

  /* Init general fields. */
  mp->g = G(L);
  mp->state = MPS_PROFILE;

  /* Init output. */
  lj_wbuf_init(&mp->out, mp_opt->writer, mp_opt->ctx, mp_opt->buf, mp_opt->len);
  dump_symtab(&mp->out, mp->g);
  create_csymtab(L, &mp->csymtab);

  /* Write prologue. */
  lj_wbuf_addn(&mp->out, ljm_header, ljm_header_len);

  if (LJ_UNLIKELY(lj_wbuf_test_flag(&mp->out, STREAM_ERRIO | STREAM_STOP))) {
    /* on_stop call may change errno value. */
    int saved_errno = lj_wbuf_errno(&mp->out);
    /* Ignore possible errors. mp->out.buf may be NULL here. */
    mp_opt->on_stop(mp_opt->ctx, mp->out.buf);
    lj_wbuf_terminate(&mp->out);
    mp->state = MPS_IDLE;
    errno = saved_errno;
    return PROFILE_ERRIO;
  }

  /* Override allocating function. */
  oalloc->allocf = lua_getallocf(L, &oalloc->state);
  lua_assert(oalloc->allocf != NULL);
  lua_assert(oalloc->allocf != memprof_allocf);
  lua_assert(oalloc->state != NULL);
  lua_setallocf(L, memprof_allocf, oalloc->state);

  return PROFILE_SUCCESS;
}

int lj_memprof_stop(struct lua_State *L) {
  struct memprof *mp = &memprof;
  struct lj_memprof_options *mp_opt = &mp->opt;
  struct alloc *oalloc = &mp->orig_alloc;
  struct lj_wbuf *out = &mp->out;
  int cb_status;

  if (mp->state == MPS_HALT) {
    errno = mp->saved_errno;
    mp->state = MPS_IDLE;
    /* wbuf was terminated before. */
    return PROFILE_ERRIO;
  }

  if (mp->state != MPS_PROFILE) return PROFILE_ERRRUN;

  if (mp->g != G(L)) return PROFILE_ERRUSE;

  mp->state = MPS_IDLE;

  lua_assert(mp->g != NULL);

  lua_assert(memprof_allocf == lua_getallocf(L, NULL));
  lua_assert(oalloc->allocf != NULL);
  lua_assert(oalloc->state != NULL);
  lua_setallocf(L, oalloc->allocf, oalloc->state);
  

  if (LJ_UNLIKELY(lj_wbuf_test_flag(out, STREAM_STOP))) {
    /* on_stop call may change errno value. */
    int saved_errno = lj_wbuf_errno(out);
    /* Ignore possible errors. out->buf may be NULL here. */
    mp_opt->on_stop(mp_opt->ctx, out->buf);
    errno = saved_errno;
    goto errio;
  }

  lj_wbuf_addbyte(out, EVENTS_FINAL);
  resolve_csymtab(L, &mp->csymtab);
  write_csymtab(L, &mp->csymtab, out);
  free_csymtab(L, mp->csymtab);
  lj_wbuf_addbyte(out, LJM_EPILOGUE_HEADER);

  lj_wbuf_flush(out);

  cb_status = mp_opt->on_stop(mp_opt->ctx, out->buf);
  if (LJ_UNLIKELY(lj_wbuf_test_flag(out, STREAM_ERRIO | STREAM_STOP) ||
                  cb_status != 0)) {
    errno = lj_wbuf_errno(out);
    goto errio;
  }

  lj_wbuf_terminate(out);
  return PROFILE_SUCCESS;
errio:
  lj_wbuf_terminate(out);
  return PROFILE_ERRIO;
}

#else /* LJ_HASMEMPROF */

int lj_memprof_start(struct lua_State *L,
                     const struct lj_memprof_options *opt) {
  UNUSED(L);
  /* Clean up resourses. Ignore possible errors. */
  opt->on_stop(opt->ctx, opt->buf);
  return PROFILE_ERRUSE;
}

int lj_memprof_stop(struct lua_State *L) {
  UNUSED(L);
  return PROFILE_ERRUSE;
}

#endif /* LJ_HASMEMPROF */
