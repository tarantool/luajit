/*
** Libunwind-based stack collector.
*/
#include "lj_stack_collector.h"

/*
** We only need local unwinding, then a special implementation
** can be selected which may run much faster than the generic
** implementation which supports both kinds of unwinding, local
** and remote.
*/
#define UNW_LOCAL_ONLY
#include <libunwind.h>

ssize_t collect_stack(void **buffer, int size)
{
  int frame_no = 0;
  unw_context_t unw_ctx;
  unw_cursor_t unw_cur;

  int rc = unw_getcontext(&unw_ctx);
  if (rc != 0)
    return -1;

  rc = unw_init_local(&unw_cur, &unw_ctx);
  if (rc != 0)
    return -1;

  for (; frame_no < size; ++frame_no) {
    unw_word_t ip;
    rc = unw_get_reg(&unw_cur, UNW_REG_IP, &ip);
    if (rc != 0)
      return -1;

    buffer[frame_no] = (void *)ip;
    rc = unw_step(&unw_cur);
    if (rc <= 0)
      break;
  }
  return frame_no;
}
