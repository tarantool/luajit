/*
** Libunwind-based stack collector.
**
** XXX: This module must be compiled and linked separately from
** other LuaJIT sources. Otherwise, the definitions from
** libunwind and libgcc can collide, leading to unwinding working
** improperly. Compiling this module separately ensures that the
** only place where libunwind is used is here.
*/

#ifndef _LJ_STACK_COLLECTOR_H
#define _LJ_STACK_COLLECTOR_H

#include <sys/types.h>

ssize_t collect_stack(void **buffer, int size);

#endif
