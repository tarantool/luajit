/*
** Memory profiler.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#ifndef _LJP_MEMPROF_H
#define _LJP_MEMPROF_H

/*
** Event stream format:
**
** stream         := symtab memprof
** symtab         := see <ljp_symtab.h>
** memprof        := prologue event* epilogue
** prologue       := 'l' 'j' 'm' version reserved
** version        := <BYTE>
** reserved       := <BYTE> <BYTE> <BYTE>
** prof-id        := <ULEB128>
** event          := event-alloc | event-realloc | event-free
** event-alloc    := event-header loc? naddr nsize
** event-realloc  := event-header loc? oaddr osize naddr nsize
** event-free     := event-header loc? oaddr osize
** event-header   := <BYTE>
** loc            := loc-lua | loc-c
** loc-lua        := sym-addr line-no
** loc-c          := sym-addr
** sym-addr       := <ULEB128>
** line-no        := <ULEB128>
** oaddr          := <ULEB128>
** naddr          := <ULEB128>
** osize          := <ULEB128>
** nsize          := <ULEB128>
** epilogue       := event-header
**
** <BYTE>   :  A single byte (no surprises here)
** <ULEB128>:  Unsigned integer represented in ULEB128 encoding
**
** (Order of bits below is hi -> lo)
**
** version: [VVVVVVVV]
**  * VVVVVVVV: Byte interpreted as a plain integer version number
**
** event-header: [FTUUSSEE]
**  * EE   : 2 bits for representing allocation event type (AEVENT_*)
**  * SS   : 2 bits for representing allocation source type (ASOURCE_*)
**  * UU   : 2 unused bits
**  * T    : Reserved. 0 for regular events, 1 for the events marked with
**           the timestamp mark. It is assumed that the time distance between
**           two marked events is approximately the same and is equal
**           to 1 second. Always zero for now.
**  * F    : 0 for regular events, 1 for epilogue's *F*inal header
**           (if F is set to 1, all other bits are currently ignored)
*/

struct lua_State;

#define LJM_CURRENT_FORMAT_VERSION 0x02

struct luam_Prof_options;

/*
** Starts profiling. Returns LUAM_PROFILE_SUCCESS on success and one of
** LUAM_PROFILE_ERR* codes otherwise. Destroyer is called in case of
** LUAM_PROFILE_ERR*.
*/
int ljp_memprof_start(struct lua_State *L, const struct luam_Prof_options *opt);

/*
** Stops profiling. Returns LUAM_PROFILE_SUCCESS on success and one of
** LUAM_PROFILE_ERR* codes otherwise. If writer() function returns zero
** on call at buffer flush, or on_stop() callback returns non-zero
** value, returns LUAM_PROFILE_ERRIO.
*/
int ljp_memprof_stop(void);

/*
** VM g is currently being profiled, behaves exactly as ljp_memprof_stop().
** Otherwise does nothing and returns LUAM_PROFILE_ERR.
*/
int ljp_memprof_stop_vm(const struct lua_State *L);

/* Check that profiler is running. */
int ljp_memprof_is_running(void);

#endif
