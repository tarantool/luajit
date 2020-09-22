/*
** Interfaces for working with LEB128/ULEB128 encoding.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#ifndef _LJ_UTILS_LEB128_H
#define _LJ_UTILS_LEB128_H

#include <stddef.h>
#include <stdint.h>

/* Maximum number of bytes needed for LEB128 encoding of any 64-bit value. */
#define LEB128_U64_MAXSIZE 10

/*
** Writes a value from an unsigned 64-bit input to a buffer of bytes.
** Buffer overflow is not checked. Returns number of bytes written.
*/
size_t write_uleb128(uint8_t *buffer, uint64_t value);

/*
** Writes a value from an signed 64-bit input to a buffer of bytes.
** Buffer overflow is not checked. Returns number of bytes written.
*/
size_t write_leb128(uint8_t *buffer, int64_t value);

/*
** Reads a value from a buffer of bytes to a uint64_t output.
** Buffer overflow is not checked. Returns number of bytes read.
*/
size_t read_uleb128(uint64_t *out, const uint8_t *buffer);

/*
** Reads a value from a buffer of bytes to a int64_t output.
** Buffer overflow is not checked. Returns number of bytes read.
*/
size_t read_leb128(int64_t *out, const uint8_t *buffer);

/*
** Reads a value from a buffer of bytes to a uint64_t output. Consumes no more
** than n bytes. Buffer overflow is not checked. Returns number of bytes read.
** If more than n bytes is about to be consumed, returns 0 without touching out.
*/
size_t read_uleb128_n(uint64_t *out, const uint8_t *buffer, size_t n);

/*
** Reads a value from a buffer of bytes to a int64_t output. Consumes no more
** than n bytes. Buffer overflow is not checked. Returns number of bytes read.
** If more than n bytes is about to be consumed, returns 0 without touching out.
*/
size_t read_leb128_n(int64_t *out, const uint8_t *buffer, size_t n);

#endif
