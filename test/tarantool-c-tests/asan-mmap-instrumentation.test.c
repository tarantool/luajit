#include "lua.h"
#include "test.h"
#include "utils.h"
#include "lj_alloc.c"
#include "lj_gc.h"

#if LUAJIT_USE_ASAN_HARDENING
#include <sanitizer/asan_interface.h>

#define MALLOC(size) mmap_probe(size)
#define FREE(ptr, size) CALL_MUNMAP(ptr, size)
#define REALLOC(ptr, osz, nsz) CALL_MREMAP(ptr, osz, nsz, CALL_MREMAP_MV)
#define IS_POISONED(ptr) __asan_address_is_poisoned(ptr)


int IS_POISONED_REGION(void *ptr, size_t size)
{
	int res = 1;
	int i = 0;
	do {
		res *= IS_POISONED(ptr + i);
	} while (res == 1 && ++i < size);
	return res;
}
#endif

static lua_State *main_LS = NULL;

static int mmap_probe_test(void *test_state)
{
#if !LUAJIT_USE_ASAN_HARDENING || LUAJIT_USE_SYSMALLOC
    UNUSED(test_state);
    return skip("Requires build with ASAN");
#else
	int res = -1;
	size_t size = DEFAULT_GRANULARITY - TOTAL_REDZONE_SIZE;
	void *p = MALLOC(size);
	size_t algn = ALIGN_SIZE(size, SIZE_ALIGNMENT) - size;

	if (p == MFAIL) {
		perror("mmap memory allocation error");
		return TEST_EXIT_FAILURE;
	}

	if (IS_POISONED_REGION(p - REDZONE_SIZE, REDZONE_SIZE) &&
	    !IS_POISONED_REGION(p, size) &&
	    IS_POISONED_REGION(p + size, algn + REDZONE_SIZE))
		res = TEST_EXIT_SUCCESS;
	else
		perror("Not correct poison and unpoison areas");
	FREE(p, size);
	return res == TEST_EXIT_SUCCESS ? TEST_EXIT_SUCCESS : TEST_EXIT_FAILURE;
#endif
}

static int munmap_test(void *test_state)
{
#if !LUAJIT_USE_ASAN_HARDENING || LUAJIT_USE_SYSMALLOC
    UNUSED(test_state);
    return skip("Requires build with ASAN");
#else
	size_t size = DEFAULT_GRANULARITY - TOTAL_REDZONE_SIZE;
	size_t algn = ALIGN_SIZE(size, SIZE_ALIGNMENT) - size;
	void *p = MALLOC(size);

	if (p == MFAIL) {
		perror("mmap memory allocation error");
		return TEST_EXIT_FAILURE;
	}

	FREE(p, size);
	if (IS_POISONED_REGION(p - REDZONE_SIZE, TOTAL_REDZONE_SIZE + size + algn))
		return TEST_EXIT_SUCCESS;
	perror("Not correct poison and unpoison areas");
	return TEST_EXIT_FAILURE;
#endif
}

static int mremap_test(void *test_state)
{
#if !LUAJIT_USE_ASAN_HARDENING || LUAJIT_USE_SYSMALLOC
    UNUSED(test_state);
    return skip("Requires build with ASAN");
#else
	int res = -1;
	size_t size = (DEFAULT_GRANULARITY >> 2) - TOTAL_REDZONE_SIZE;
	size_t new_size = (DEFAULT_GRANULARITY >> 1) - TOTAL_REDZONE_SIZE;
	void *p = MALLOC(size);

	if (p == MFAIL) {
		perror("mmap memory allocation error");
		return TEST_EXIT_FAILURE;
	}

	void *newptr = REALLOC(p, size, new_size);
	if (newptr == MFAIL) {
		perror("mremap return MFAIL");
		FREE(p, size);
		return TEST_EXIT_FAILURE;
	}

	if (IS_POISONED_REGION(newptr - REDZONE_SIZE, REDZONE_SIZE) &&
	    !IS_POISONED_REGION(newptr, new_size) &&
	    IS_POISONED_REGION(newptr + new_size, REDZONE_SIZE))
		res = TEST_EXIT_SUCCESS;
	else
		perror("Not correct poison and unpoison areas");

	FREE(newptr, new_size);
	return res == TEST_EXIT_SUCCESS ? TEST_EXIT_SUCCESS : TEST_EXIT_FAILURE;
#endif
}

int main(void)
{
	lua_State *L = utils_lua_init();
	main_LS = L;

	const struct test_unit tgroup[] = {
		test_unit_def(mmap_probe_test),
		test_unit_def(munmap_test),
		test_unit_def(mremap_test)
	};

	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
}
