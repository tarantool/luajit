/*
** Low-level event streaming for LuaJIT Profiler.
** NB! Please note that all events are streamed inside a signal handler. This
** means effectively that only async-signal-safe library functions and syscalls
** MUST be used for streaming. Check with `man 7 signal` when in doubt.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#ifndef _LJP_WRITE_H
#define _LJP_WRITE_H

#include <stdint.h>

/*
** Event stream format:
**
** stream       := prologue event* epilogue
** prologue     := 'l' 'j' 'p' version reserved prof-id start-time interval \
**                 so-num so-objects
** so-num       := <ULEB128>
** so-objects   := so-info*
** so-info      := so-path so-base
** so-path      := string
** so-base      := <ULEB128>
** version      := <BYTE>
** reserved     := <BYTE> <BYTE> <BYTE>
** prof-id      := <ULEB128>
** start-time   := <ULEB128>
** interval     := <ULEB128>
** event        := event-header frame*
** event-header := <BYTE>
** frame        := frame-header frame-info
** frame-header := <BYTE>
** frame-info   := frame-id frame-sym? | frame-id trace-gen sym-trace?
** frame-id     := <ULEB128>
** frame-sym    := sym-lua | sym-ff
** sym-lua      := chunk-name loc-line
** sym-ff       := ff-name
** trace-gen    := <ULEB128>
** sym-trace    := chunk-name start-line
** chunk-name   := string
** ff-name      := string
** loc-line     := <ULEB128>
** trace-num    := <ULEB128>
** start-line   := <ULEB128>
** epilogue     := event-header end-time num-samples num-overruns
** end-time     := <ULEB128>
** num-samples  := <ULEB128>
** num-overruns := <ULEB128>
**
** string         := string-len string-payload
** string-len     := <ULEB128>
** string-payload := <BYTE> {string-len}
**
** Notes.
** 1) For strings shorter than 128 bytes (most likely scenario in our case)
** we write the same amount of data (1-byte ULEB128 + actual payload) as we
** would have written with straightforward serialization (actual payload + \0),
** but make parsing easier.
** 2) start-time and end-time must resolve to microseconds.
**
** <BYTE>   :  A single byte (no surprises here)
** <ULEB128>:  Unsigned integer represented in ULEB128 encoding
**
** (Order of bits below is hi -> lo)
**
** version: [VVVVVVVV]
**  * VVVVVVVV: Byte interpreted as a plain numeric version number
**
** event-header: [FUUUSSSS]
**  * SSSS: 4 bits for representing VM state
**  * UUU : 3 unused bits
**  * F   : 0 for regular profiler events, 1 for epilogue's *F*inal header
**          (if F is set to 1, all other bits are currently ignored)
**
** Presence of frame elements inside the event elements depends on VM state
** encoded in event-header. For now, only following VM states assume frame
** elements: LFUNC, FFUNC, CFUNC, TRACE.
** For other VM states only RIP value is dumped to be able to determine
** particular shared object which has been in use at the time.
**
** frame-header: [UUFFFEBT]
**  * T  : Is current frame a top frame?
**  * B  : Is current frame a bottom frame?
**  * E  : Is frame-sym data explicitly set after frame-id in the stream?
**  * FFF: 3 bits for representing type of callable object
**         (Lua function, fast function, compiled trace)
**  * UU : 2 unused bits
*/

#define LJP_FRAME_MIDDLE 0x0
#define LJP_FRAME_TOP 0x1
#define LJP_FRAME_BOTTOM 0x2
#define LJP_FRAME_EXPLICIT_SYMBOL 0x4

/* Main scope of a chunk. */
#define LJP_FRAME_TYPE_MAIN 0x1
/* Call to a Lua function, except the main scope. */
#define LJP_FRAME_TYPE_LFUNC 0x2
/* Call to a registered C function. */
#define LJP_FRAME_TYPE_CFUNC 0x3
/* Call to a fast function. */
#define LJP_FRAME_TYPE_FFUNC 0x4
/* JIT-compiled trace. */
#define LJP_FRAME_TYPE_TRACE 0x5
/*
** In case VM is in a state when no per-frame data is required for reporting
** there should be some generic pseudo frame type to stand for such states
** in profiler binary stream.
*/
#define LJP_FRAME_TYPE_HOST 0x6

/*
** frame-id is required according to the format, the constant below is used as
** a dummy frame ID for the main chunk frame. Rationale:
**  1. Making frame-id optional would complicate parsing a bit.
**  2. In real world not that much code is run in the context of the main frame,
**     so writing an extra byte would not add much size overhead.
*/
#define FRAME_ID_MAIN_LUA 0x0
#define LJP_CURRENT_FORMAT_VERSION 0x04
#define LJP_EPILOGUE_BIT 0x80

/*
** Although event stream format allows streaming full stack traces, current
** implementation streams top-most frame only, so each pseudo-stack trace
** always consists of a single frame which is both top and bottom. Below is
** defined for convenience.
*/
#define LJP_FRAME_FOR_LEAF_PROFILE (LJP_FRAME_TOP | LJP_FRAME_BOTTOM)

/* Stream errors. */
#define STREAM_ERR_IO 0x1
#define STREAM_STOP   0x2

typedef size_t (*ljp_writer)(const void **data, size_t len, void *opt);

/* Write buffer for profilers. */
struct ljp_buffer {
  /*
  ** Buffer writer which will called at buffer write.
  ** Should return amount of written bytes on success or zero in case of error.
  */
  ljp_writer writer;
  /* Options to writer function. */
  void *opt;
  /* Buffer size. */
  size_t size;
  /* Saved errno in case of error. */
  int saved_errno;
  /* Start of buffer. */
  uint8_t *buf;
  /* Current position in buffer. */
  uint8_t *pos;
  /* Internal flags. */
  volatile uint8_t flags;
};

/* Write string. */
void ljp_write_string(struct ljp_buffer *buf, const char *s);

/* Write single byte. */
void ljp_write_byte(struct ljp_buffer *buf, uint8_t b);

/* Write uint64_t in uleb128 format. */
void ljp_write_u64(struct ljp_buffer *buf, uint64_t n);

/* Immediatly flush buffer to disk. */
void ljp_write_flush_buffer(struct ljp_buffer *buf);

/* Write new trace. */
void ljp_write_new_trace(struct ljp_buffer *buf, uint8_t frame_type,
			 uint64_t generation, uint64_t traceno,
			 const char *name, uint64_t line);

/* Write already marked trace. */
void ljp_write_marked_trace(struct ljp_buffer *buf, uint8_t frame_type,
			    uint64_t generation, uint64_t traceno);
/* Write single FFUNC frame. */
void ljp_write_ffunc(struct ljp_buffer *buf, uint8_t frame_type, uint64_t ffid);

/* Write single CFUNC frame. */
void ljp_write_cfunc(struct ljp_buffer *buf, uint8_t frmae_type, uint64_t cf);

/* Write stub frame (MAIN_LUA). */
void ljp_write_main_lua(struct ljp_buffer *buf, uint8_t frame_type);

/* Bottom frame for callgraph. */
void ljp_write_bottom_frame(struct ljp_buffer *buf);

/* Write new LFUNC. */
void ljp_write_new_lfunc(struct ljp_buffer *buf, uint8_t frame_type,
			 uint64_t pt, const char *name, uint64_t fl);

/* Already marked LFUNC. */
void ljp_write_marked_lfunc(struct ljp_buffer *buf, uint8_t frame_type,
			    uint64_t pt);

/*
** For one of the following VM states:
** C, GC, INTERP, RECORD, EXIT, OPT, ASM write RIP value as profiling data.
*/
void ljp_write_hvmstate(struct ljp_buffer *buf, uint64_t addr);

/* Init buffer. */
void ljp_write_init(struct ljp_buffer *buf, ljp_writer writer, void *opt,
		    uint8_t *mem, size_t size);

/* Check flags. */
int ljp_write_test_flag(const struct ljp_buffer *buf, uint8_t flag);

/* Return saved errno. */
int ljp_write_errno(const struct ljp_buffer *buf);

/* Set pointers to NULL and reset flags. */
void ljp_write_terminate(struct ljp_buffer *buf);

#endif
