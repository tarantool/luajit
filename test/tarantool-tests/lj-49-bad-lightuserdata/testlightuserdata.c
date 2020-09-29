#include <lua.h>
#include <lauxlib.h>

#include <sys/mman.h>
#include <unistd.h>

#undef NDEBUG
#include <assert.h>

#define START ((void *)-1)

static int crafted_ptr(lua_State *L)
{
	/*
	 * We know that for arm64 at least 48 bits are available.
	 * So emulate manually push of lightuseradata within
	 * this range.
	 */
	void *longptr = (void *)(1llu << 48);
	lua_pushlightuserdata(L, longptr);
	assert(longptr == lua_topointer(L, -1));
	/* Clear our stack. */
	lua_pop(L, 0);
	lua_pushboolean(L, 1);
	return 1;
}

static int mmaped_ptr(lua_State *L)
{
	/*
	 * If start mapping address is not NULL, then the kernel
	 * takes it as a hint about where to place the mapping, so
	 * we try to get the highest memory address by hint, that
	 * equals to -1.
	 */
	const size_t pagesize = getpagesize();
	void *mmaped = mmap(START, pagesize, PROT_NONE, MAP_PRIVATE | MAP_ANON,
			    -1, 0);
	if (mmaped != MAP_FAILED) {
		lua_pushlightuserdata(L, mmaped);
		assert(mmaped == lua_topointer(L, -1));
		assert(munmap(mmaped, pagesize) == 0);
	}
	/* Clear our stack. */
	lua_pop(L, 0);
	lua_pushboolean(L, 1);
	return 1;
}

static const struct luaL_Reg testlightuserdata[] = {
	{"crafted_ptr", crafted_ptr},
	{"mmaped_ptr", mmaped_ptr},
	{NULL, NULL}
};

LUA_API int luaopen_testlightuserdata(lua_State *L)
{
	luaL_register(L, "testlightuserdata", testlightuserdata);
	return 1;
}

