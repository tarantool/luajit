/*
** Implementation of the Lua symbol table dumper.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#include "lj_obj.h"
#include "profile/ljp_write.h"
#include "profile/ljp_symtab.h"

#define LJS_CURRENT_VERSION 2

static const unsigned char ljs_header[] = {'l', 'j', 's', LJS_CURRENT_VERSION,
					   0x0, 0x0, 0x0};

static void symtab_write_prologue(struct ljp_buffer *out,
				  const struct global_State *g)
{
  const size_t len = sizeof(ljs_header) / sizeof(ljs_header[0]);
  size_t i = 0;

  for (; i < len; i++)
    ljp_write_byte(out, ljs_header[i]);
}

void ljp_symtab_write(struct ljp_buffer *out, const struct global_State *g)
{
  const GCobj *o;
  const GCRef *iter = &g->gc.root;

  symtab_write_prologue(out, g);

  while (NULL != (o = gcref(*iter))) {
    switch (o->gch.gct) {
    case (~LJ_TPROTO): {
      const GCproto *pt = gco2pt(o);
      ljp_write_byte(out, SYMTAB_LFUNC);
      ljp_write_u64(out, (uintptr_t)pt);
      ljp_write_string(out, proto_chunknamestr(pt));
      ljp_write_u64(out, (uint64_t)pt->firstline);
      break;
    }
    case (~LJ_TTRACE): {
      /* TODO: Implement dumping a trace info */
      break;
    }
    default: {
      break;
    }
    }
    iter = &o->gch.nextgc;
  }

  ljp_write_byte(out, SYMTAB_FINAL);
}
