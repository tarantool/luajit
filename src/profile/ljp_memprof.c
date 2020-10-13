/*
** Implementation of memory profiler.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#include <errno.h>

#include "profile/ljp_memprof.h"
#include "lmisclib.h"
#include "lj_def.h"
#include "lj_arch.h"

#if LJ_HASMEMPROF

#if LJ_IS_THREAD_SAFE
#include <pthread.h>
#endif

#include "lua.h"

#include "lj_obj.h"
#include "lj_frame.h"
#include "lj_debug.h"
#include "lj_gc.h"
#include "profile/ljp_symtab.h"
#include "profile/ljp_write.h"

/* Allocation events: */
#define AEVENT_ALLOC   ((uint8_t)1)
#define AEVENT_FREE    ((uint8_t)2)
#define AEVENT_REALLOC ((uint8_t)(AEVENT_ALLOC | AEVENT_FREE))

/* Allocation sources: */
#define ASOURCE_INT   ((uint8_t)(1 << 2))
#define ASOURCE_LFUNC ((uint8_t)(2 << 2))
#define ASOURCE_CFUNC ((uint8_t)(3 << 2))

/* Aux bits: */

/*
** Reserved. There is ~1 second between each two events marked with this flag.
** This will possibly be used later to implement dumps of the evolving heap.
*/
#define LJM_TIMESTAMP ((uint8_t)(0x40))

#define LJM_EPILOGUE_HEADER 0x80

enum memprof_state {
  /* memprof is not running. */
  MPS_IDLE,
  /* memprof is running. */
  MPS_PROFILE,
  /*
  ** Stopped in case of stopped stream.
  ** Saved errno is returned to user at memprof_stop.
  */
  MPS_HALT
};

struct alloc {
  lua_Alloc allocf; /* Allocating function. */
  void *state; /* Opaque allocator's state. */
};

struct memprof {
  global_State *g; /* Profiled VM. */
  enum memprof_state state; /* Internal state. */
  struct ljp_buffer out; /* Output accumulator. */
  struct alloc orig_alloc; /* Original allocator. */
  struct luam_Prof_options opt; /* Profiling options. */
  int saved_errno; /* Saved errno when profiler deinstrumented. */
};

#if LJ_IS_THREAD_SAFE

pthread_mutex_t memprof_mutex = PTHREAD_MUTEX_INITIALIZER;

static LJ_AINLINE int memprof_lock(void)
{
  return pthread_mutex_lock(&memprof_mutex);
}

static LJ_AINLINE int memprof_unlock(void)
{
  return pthread_mutex_unlock(&memprof_mutex);
}

#else /* LJ_IS_THREAD_SAFE */

#define memprof_lock()
#define memprof_unlock()

#endif /* LJ_IS_THREAD_SAFE */

static struct memprof memprof = {0};

const unsigned char ljm_header[] = {'l', 'j', 'm', LJM_CURRENT_FORMAT_VERSION,
				    0x0, 0x0, 0x0};

static void memprof_write_lfunc(struct ljp_buffer *out, uint8_t header,
				GCfunc *fn, struct lua_State *L,
				cTValue *nextframe)
{
  const BCLine line = lj_debug_frameline(L, fn, nextframe);
  ljp_write_byte(out, header | ASOURCE_LFUNC);
  ljp_write_u64(out, (uintptr_t)funcproto(fn));
  ljp_write_u64(out, line >= 0 ? (uintptr_t)line : 0);
}

static void memprof_write_cfunc(struct ljp_buffer *out, uint8_t header,
				const GCfunc *fn)
{
  ljp_write_byte(out, header | ASOURCE_CFUNC);
  ljp_write_u64(out, (uintptr_t)fn->c.f);
}

static void memprof_write_ffunc(struct ljp_buffer *out, uint8_t header,
				GCfunc *fn, struct lua_State *L,
				cTValue *frame)
{
  cTValue *pframe = frame_prev(frame);
  GCfunc *pfn = frame_func(pframe);

  /*
  ** NB! If a fast function is called by a Lua function, report the
  ** Lua function for more meaningful output. Otherwise report the fast
  ** function as a C function.
  */
  if (pfn != NULL && isluafunc(pfn))
    memprof_write_lfunc(out, header, pfn, L, frame);
  else
    memprof_write_cfunc(out, header, fn);
}

static void memprof_write_func(struct memprof *mp, uint8_t header)
{
  struct ljp_buffer *out = &mp->out;
  lua_State *L = gco2th(gcref(mp->g->mem_L));
  cTValue *frame = L->base - 1;
  GCfunc *fn;

  fn = frame_func(frame);

  if (isluafunc(fn))
    memprof_write_lfunc(out, header, fn, L, NULL);
  else if (isffunc(fn))
    memprof_write_ffunc(out, header, fn, L, frame);
  else if (iscfunc(fn))
    memprof_write_cfunc(out, header, fn);
  else
    lua_assert(0);
}

static void memprof_write_hvmstate(struct memprof *mp, uint8_t header)
{
  ljp_write_byte(&mp->out, header | ASOURCE_INT);
}

/*
** NB! In ideal world, we should report allocations from traces as well.
** But since traces must follow the semantics of the original code, behaviour of
** Lua and JITted code must match 1:1 in terms of allocations, which makes
** using memprof with enabled JIT virtually redundant. Hence the stub below.
*/
static void memprof_write_trace(struct memprof *mp, uint8_t header)
{
  ljp_write_byte(&mp->out, header | ASOURCE_INT);
}

typedef void (*memprof_writer)(struct memprof *mp, uint8_t header);

static const memprof_writer memprof_writers[] = {
  memprof_write_hvmstate, /* LJ_VMST_INTERP */
  memprof_write_func, /* LJ_VMST_LFUNC */
  memprof_write_func, /* LJ_VMST_FFUNC */
  memprof_write_func, /* LJ_VMST_CFUNC */
  memprof_write_hvmstate, /* LJ_VMST_GC */
  memprof_write_hvmstate, /* LJ_VMST_EXIT */
  memprof_write_hvmstate, /* LJ_VMST_RECORD */
  memprof_write_hvmstate, /* LJ_VMST_OPT */
  memprof_write_hvmstate, /* LJ_VMST_ASM */
  memprof_write_trace /* LJ_VMST_TRACE */
};

static void memprof_write_caller(struct memprof *mp, uint8_t aevent)
{
  const global_State *g = mp->g;
  const uint32_t _vmstate = (uint32_t)~g->vmstate;
  const uint32_t vmstate = _vmstate < LJ_VMST_TRACE ? _vmstate : LJ_VMST_TRACE;
  const uint8_t header = aevent;

  memprof_writers[vmstate](mp, header);
}

static int memprof_stop(const struct lua_State *L);

static void *memprof_allocf(void *ud, void *ptr, size_t osize, size_t nsize)
{
  struct memprof *mp = &memprof;
  struct alloc *oalloc = &mp->orig_alloc;
  struct ljp_buffer *out = &mp->out;
  void *nptr;

  lua_assert(MPS_PROFILE == mp->state);
  lua_assert(oalloc->allocf != memprof_allocf);
  lua_assert(oalloc->allocf != NULL);
  lua_assert(ud == oalloc->state);

  nptr = oalloc->allocf(ud, ptr, osize, nsize);

  if (nsize == 0) {
    memprof_write_caller(mp, AEVENT_FREE);
    ljp_write_u64(out, (uintptr_t)ptr);
    ljp_write_u64(out, (uint64_t)osize);
  } else if (ptr == NULL) {
    memprof_write_caller(mp, AEVENT_ALLOC);
    ljp_write_u64(out, (uintptr_t)nptr);
    ljp_write_u64(out, (uint64_t)nsize);
  } else {
    memprof_write_caller(mp, AEVENT_REALLOC);
    ljp_write_u64(out, (uintptr_t)ptr);
    ljp_write_u64(out, (uint64_t)osize);
    ljp_write_u64(out, (uintptr_t)nptr);
    ljp_write_u64(out, (uint64_t)nsize);
  }

  /* Deinstrument memprof if required. */
  if (LJ_UNLIKELY(ljp_write_test_flag(out, STREAM_STOP)))
    memprof_stop(NULL);

  return nptr;
}

static void memprof_write_prologue(struct ljp_buffer *out)
{
  size_t i = 0;
  const size_t len = sizeof(ljm_header) / sizeof(ljm_header[0]);

  for (; i < len; i++)
    ljp_write_byte(out, ljm_header[i]);
}

int ljp_memprof_start(struct lua_State *L, const struct luam_Prof_options *opt)
{
  struct memprof *mp = &memprof;
  struct alloc *oalloc = &mp->orig_alloc;

  lua_assert(opt->writer != NULL && opt->on_stop != NULL);
  lua_assert(opt->buf != NULL && opt->len != 0);

  memprof_lock();

  if (mp->state != MPS_IDLE) {
    memprof_unlock();
    return LUAM_PROFILE_ERR;
  }

  /* Discard possible old errno. */
  mp->saved_errno = 0;

  /* Init options: */
  memcpy(&mp->opt, opt, sizeof(*opt));

  /* Init general fields: */
  mp->g = G(L);
  mp->state = MPS_PROFILE;

  /* Init output: */
  ljp_write_init(&mp->out, mp->opt.writer, mp->opt.ctx, mp->opt.buf,
		 mp->opt.len);
  ljp_symtab_write(&mp->out, mp->g);
  memprof_write_prologue(&mp->out);

  if (LJ_UNLIKELY(ljp_write_test_flag(&mp->out, STREAM_ERR_IO) ||
		  ljp_write_test_flag(&mp->out, STREAM_STOP))) {
    /* on_stop call may change errno value. */
    int saved_errno = ljp_write_errno(&mp->out);
    mp->opt.on_stop(mp->opt.ctx, mp->opt.buf);
    ljp_write_terminate(&mp->out);
    mp->state = MPS_IDLE;
    memprof_unlock();
    errno = saved_errno;
    return LUAM_PROFILE_ERRIO;
  }

  /* Override allocating function: */
  oalloc->allocf = lua_getallocf(L, &oalloc->state);
  lua_assert(oalloc->allocf != NULL);
  lua_assert(oalloc->allocf != memprof_allocf);
  lua_assert(oalloc->state != NULL);
  lua_setallocf(L, memprof_allocf, oalloc->state);

  memprof_unlock();
  return LUAM_PROFILE_SUCCESS;
}

static int memprof_stop(const struct lua_State *L)
{
  struct memprof *mp = &memprof;
  struct alloc *oalloc = &mp->orig_alloc;
  struct ljp_buffer *out = &mp->out;
  int return_status = LUAM_PROFILE_SUCCESS;
  int saved_errno = 0;
  struct lua_State *main_L;
  int cb_status;

  memprof_lock();

  if (mp->state == MPS_HALT) {
    errno = mp->saved_errno;
    mp->state = MPS_IDLE
    memprof_unlock();
    return LUAM_PROFILE_ERRIO;
  }

  if (mp->state != MPS_PROFILE) {
    memprof_unlock();
    return LUAM_PROFILE_ERR;
  }

  if (L != NULL && mp->g != G(L)) {
    memprof_unlock();
    return LUAM_PROFILE_ERR;
  }

  mp->state = MPS_IDLE;

  lua_assert(mp->g != NULL);
  main_L = mainthread(mp->g);

  lua_assert(memprof_allocf == lua_getallocf(main_L, NULL));
  lua_assert(oalloc->allocf != NULL);
  lua_assert(oalloc->state != NULL);
  lua_setallocf(main_L, oalloc->allocf, oalloc->state);

  if (LJ_UNLIKELY(ljp_write_test_flag(out, STREAM_STOP))) {
    lua_assert(ljp_write_test_flag(out, STREAM_ERR_IO));
    mp->state = MPS_HALT;
    /* on_stop call may change errno value. */
    mp->saved_errno = ljp_write_errno(out);
    /* Ignore possible errors. mp->opt.buf == NULL here. */
    mp->opt.on_stop(mp->opt.ctx, mp->opt.buf);
    ljp_write_terminate(out);
    memprof_unlock();
    return LUAM_PROFILE_ERRIO;
  }
  ljp_write_byte(out, LJM_EPILOGUE_HEADER);

  ljp_write_flush_buffer(out);

  cb_status = mp->opt.on_stop(mp->opt.ctx, mp->opt.buf);
  if (LJ_UNLIKELY(ljp_write_test_flag(out, STREAM_ERR_IO) || cb_status != 0)) {
    saved_errno = ljp_write_errno(out);
    return_status = LUAM_PROFILE_ERRIO;
  }

  ljp_write_terminate(out);

  memprof_unlock();
  errno = saved_errno;
  return return_status;
}

int ljp_memprof_stop(void)
{
  return memprof_stop(NULL);
}

int ljp_memprof_stop_vm(const struct lua_State *L)
{
  return memprof_stop(L);
}

int ljp_memprof_is_running(void)
{
  struct memprof *mp = &memprof;
  int running;

  memprof_lock();
  running = mp->state == MPS_PROFILE;
  memprof_unlock();

  return running;
}

#else /* LJ_HASMEMPROF */

int ljp_memprof_start(struct lua_State *L, const struct luam_Prof_options *opt)
{
  UNUSED(L);
  UNUSED(opt);
  return LUAM_PROFILE_ERR;
}

int ljp_memprof_stop(void)
{
  return LUAM_PROFILE_ERR;
}

int ljp_memprof_stop_vm(const struct lua_State *L)
{
  UNUSED(L);
  return LUAM_PROFILE_ERR;
}

int ljp_memprof_is_running(void)
{
  return 0;
}

#endif /* LJ_HASMEMPROF */
