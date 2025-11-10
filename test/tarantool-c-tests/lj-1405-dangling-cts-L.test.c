#include "lua.h"

#include "test.h"
#include "utils.h"

/* XXX: Still need normal assert inside `call_callback()`. */
#undef NDEBUG
#include <assert.h>

typedef void (*callback_t)(void);
static callback_t callback = NULL;

/* Function to be called via FFI. */
extern void add_callback(callback_t cb)
{
	callback = cb;
}

static void call_callback(void)
{
	assert(callback != NULL);
	callback();
}

static int dangling_cts_L(void *test_state)
{
	lua_State *L = utils_lua_init();
	luaopen_ffi(L);
	const char code[] = {
		" local ffi = require('ffi')                               \n" \
		" ffi.cdef [[                                              \n" \
		"   struct test { int a; };                                \n" \
		"   void add_callback(void (*cb)(void a));                 \n" \
		    /* Simple finalizer, nop. */
		"   int getpid(void);                                      \n" \
		" ]]                                                       \n" \
		"                                                          \n" \
		" local C = ffi.C                                          \n" \
		"                                                          \n" \
		" local function nop() end                                 \n" \
		/* Collected later. Set `cts->L` in the finalizer. */
		" ffi.gc(ffi.new('struct test'), C.getpid);                \n" \
		/* Callback to be called on the old `cts->L`. */
		" C.add_callback(ffi.cast('void (*)(void)', nop))          \n"
	};
	if (luaL_dostring(L, code) != LUA_OK) {
		test_comment("error running Lua chunk: %s",
			     lua_tostring(L, -1));
		bail_out("error running Lua chunk");
	}
	lua_State* newL = lua_newthread(L);
	/* Remove `newL` from `L`. */
	lua_pop(L, 1);
	/* Set `cts->L = newL` in the finalizer. */
	lua_gc(newL, LUA_GCCOLLECT, 0);
	/* Just to be sure we don't use it anymore. */
	newL = NULL;
	/* Collect `newL`. */
	lua_gc(L, LUA_GCCOLLECT, 0);
	/* Use after free before the patch. */
	call_callback();
	utils_lua_close(L);
	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	const struct test_unit tgroup[] = {
		test_unit_def(dangling_cts_L),
	};
	return test_run_group(tgroup, NULL);
}
