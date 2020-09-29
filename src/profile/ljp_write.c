/*
** Low-level writer for LuaJIT Profiler.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#include <unistd.h>
#include <errno.h>

#include "profile/ljp_write.h"
#include "utils/leb128.h"
#include "lj_def.h"

/*
** memcpy from the standard C library is not guaranteed to be async-signal-safe.
** Common sense might tell us that it should be async-signal-safe (at least
** because it is unlikely that memcpy will allocate anything dynamically),
** but the standard is always the standard. So LuaJIT offers its own
** implementation of memcpy. Of course it will never be as fast as the system
** memcpy, but it will be guaranteed to always stay async-signal-safe. Feel
** free to remove the define below to fall-back to the system memcpy if the
** custom implementation becomes a botlleneck, but this is at your own risk.
** You are warned:)
*/
#define USE_CUSTOM_LJ_MEMCPY

#ifdef USE_CUSTOM_LJ_MEMCPY
/*
** Behaves exactly as memcpy from the standard C library with following caveats:
** - Guaranteed to be async-signal-safe.
** - Does *not* handle unaligned byte stores.
** - src cannot be declared as (const void *restrict) unless we start
**   supporting C99 explicitly. Possible overlapping of dst in src is ignored.
*/
#define COPY_BUFFER_TYPE uint64_t
#define COPY_BUFFER_SIZE sizeof(COPY_BUFFER_TYPE)

static void *write_memcpy(void *dst, const void *src, size_t n)
{
  size_t loops;
  size_t i;
  uint8_t *dst_pos = (uint8_t *)dst;
  const uint8_t *src_pos = (const uint8_t *)src;

  loops = n / COPY_BUFFER_SIZE;
  for (i = 0; i < loops; i++) {
    *(COPY_BUFFER_TYPE *)dst_pos = *(const COPY_BUFFER_TYPE *)src_pos;
    dst_pos += COPY_BUFFER_SIZE;
    src_pos += COPY_BUFFER_SIZE;
  }

  loops = n % COPY_BUFFER_SIZE;
  for (i = 0; i < loops; i++) {
    *dst_pos = *src_pos;
    dst_pos++;
    src_pos++;
  }

  return dst;
}
#else /* !USE_CUSTOM_LJ_MEMCPY */
#define write_memcpy memcpy
#endif /* USE_CUSTOM_LJ_MEMCPY */

static LJ_AINLINE void write_set_io_error(struct ljp_buffer *buf)
{
  buf->saved_errno = errno;
  buf->flags |= STREAM_ERR_IO;
}

static LJ_AINLINE void write_set_stop(struct ljp_buffer *buf)
{
  buf->flags |= STREAM_STOP;
}

static LJ_AINLINE void write_set_frame_type(uint8_t *frame_type, uint8_t type)
{
  *frame_type |= (type << 3);
}

static LJ_AINLINE void write_set_frame_flag(uint8_t *frame_type, uint8_t flag)
{
  *frame_type |= flag;
}

/* Wraps a write syscall ensuring all data have been written. */
static void write_buffer_sys(struct ljp_buffer *buffer, const void **data,
			     size_t len)
{
  void *opt = buffer->opt;
  size_t written;

  lua_assert(!ljp_write_test_flag(buffer, STREAM_STOP));

  written = buffer->writer(data, len, opt);

  if (LJ_UNLIKELY(written < len)) {
    write_set_io_error(buffer);
    if (*data == NULL)
      write_set_stop(buffer);
  }
}

static LJ_AINLINE size_t write_bytes_buffered(const struct ljp_buffer *buf)
{
  return (size_t)(buf->pos - buf->buf);
}

static LJ_AINLINE int write_buffer_has(const struct ljp_buffer *buf, size_t n)
{
  return (buf->size - write_bytes_buffered(buf)) >= n;
}

void ljp_write_flush_buffer(struct ljp_buffer *buf)
{
  lua_assert(!ljp_write_test_flag(buf, STREAM_STOP));

  write_buffer_sys(buf, (const void **)&buf->buf, write_bytes_buffered(buf));
  buf->pos = buf->buf;
}

void ljp_write_init(struct ljp_buffer *buf, ljp_writer writer, void *opt,
		    uint8_t *mem, size_t size)
{
  buf->opt = opt;
  buf->writer = writer;
  buf->buf = mem;
  buf->pos = mem;
  buf->size = size;
  buf->flags = 0;
  buf->saved_errno = 0;
}

void ljp_write_terminate(struct ljp_buffer *buf)
{
  ljp_write_init(buf, NULL, NULL, NULL, 0);
}

static LJ_AINLINE void write_reserve(struct ljp_buffer *buf, size_t n)
{
  if (LJ_UNLIKELY(!write_buffer_has(buf, n)))
    ljp_write_flush_buffer(buf);
}

/* Writes a byte to the output buffer. */
void ljp_write_byte(struct ljp_buffer *buf, uint8_t b)
{
  if (LJ_UNLIKELY(ljp_write_test_flag(buf, STREAM_STOP)))
    return;
  write_reserve(buf, sizeof(b));
  *buf->pos++ = b;
}

/* Writes an unsigned integer which is at most 64 bits long to the output. */
void ljp_write_u64(struct ljp_buffer *buf, uint64_t n)
{
  if (LJ_UNLIKELY(ljp_write_test_flag(buf, STREAM_STOP)))
    return;
  write_reserve(buf, LEB128_U64_MAXSIZE);
  buf->pos += (ptrdiff_t)write_uleb128(buf->pos, n);
}

/* Writes n bytes from an arbitrary buffer src to the output. */
static void write_buffer(struct ljp_buffer *buf, const void *src, size_t n)
{
  if (LJ_UNLIKELY(ljp_write_test_flag(buf, STREAM_STOP)))
    return;
  /*
  ** Very unlikely: We are told to write a large buffer at once.
  ** Buffer not belong to us so we must to pump data
  ** through buffer.
  */
  while (LJ_UNLIKELY(n > buf->size)) {
    ljp_write_flush_buffer(buf);
    write_memcpy(buf->pos, src, buf->size);
    buf->pos += (ptrdiff_t)buf->size;
    n -= buf->size;
  }

  write_reserve(buf, n);
  write_memcpy(buf->pos, src, n);
  buf->pos += (ptrdiff_t)n;
}

/* Writes a \0-terminated C string to the output buffer. */
void ljp_write_string(struct ljp_buffer *buf, const char *s)
{
  const size_t l = strlen(s);

  ljp_write_u64(buf, (uint64_t)l);
  write_buffer(buf, s, l);
}

/* Writes common part of the frame (frame-header and frame-id) to the output. */
static LJ_AINLINE void write_frame_common(struct ljp_buffer *buf,
					  uint8_t header, uint64_t id)
{
  ljp_write_byte(buf, header);
  ljp_write_u64(buf, id);
}

void ljp_write_main_lua(struct ljp_buffer *buf, uint8_t frame_type)
{
  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_MAIN);
  write_frame_common(buf, frame_type, FRAME_ID_MAIN_LUA);
}

void ljp_write_marked_lfunc(struct ljp_buffer *buf, uint8_t frame_type,
			    uint64_t pt)
{
  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_LFUNC);
  write_frame_common(buf, frame_type, (uint64_t)pt);
}

void ljp_write_new_lfunc(struct ljp_buffer *buf, uint8_t frame_type,
			 uint64_t pt, const char *name, uint64_t fl)
{
  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_LFUNC);
  write_set_frame_flag(&frame_type, LJP_FRAME_EXPLICIT_SYMBOL);
  write_frame_common(buf, frame_type, pt);
  ljp_write_string(buf, name);
  ljp_write_u64(buf, fl);
}

void ljp_write_bottom_frame(struct ljp_buffer *buf)
{
  uint8_t type = LJP_FRAME_BOTTOM;

  write_set_frame_type(&type, LJP_FRAME_TYPE_MAIN);
  write_frame_common(buf, type, FRAME_ID_MAIN_LUA);
}

void ljp_write_cfunc(struct ljp_buffer *buf, uint8_t frame_type, uint64_t cf)
{
  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_CFUNC);
  write_frame_common(buf, frame_type, cf);
}

void ljp_write_ffunc(struct ljp_buffer *buf, uint8_t frame_type, uint64_t ffid)
{
  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_FFUNC);
  write_frame_common(buf, frame_type, ffid);
}

void ljp_write_hvmstate(struct ljp_buffer *buf, uint64_t addr)
{
  uint8_t frame_type = LJP_FRAME_FOR_LEAF_PROFILE;

  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_HOST);
  write_frame_common(buf, frame_type, addr);
}

void ljp_write_new_trace(struct ljp_buffer *buf, uint8_t frame_type,
			 uint64_t generation, uint64_t traceno,
			 const char *name, uint64_t line)
{
  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_TRACE);
  write_set_frame_flag(&frame_type, LJP_FRAME_EXPLICIT_SYMBOL);

  write_frame_common(buf, frame_type, (uint64_t)traceno);
  ljp_write_u64(buf, generation);
  ljp_write_string(buf, name);
  ljp_write_u64(buf, line);
}

void ljp_write_marked_trace(struct ljp_buffer *buf, uint8_t frame_type,
			    uint64_t generation, uint64_t traceno)
{
  write_set_frame_type(&frame_type, LJP_FRAME_TYPE_TRACE);
  write_frame_common(buf, frame_type, (uint64_t)traceno);
  ljp_write_u64(buf, generation);
}

int ljp_write_test_flag(const struct ljp_buffer *buf, uint8_t flag)
{
  return buf->flags & flag;
}

int ljp_write_errno(const struct ljp_buffer *buf)
{
  return buf->saved_errno;
}
