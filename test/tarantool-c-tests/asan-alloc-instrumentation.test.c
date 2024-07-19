#include "lua.h"
#include "test.h"
#include "utils.h"
#include "lj_alloc.c"
#include "lj_gc.h"

#if LUAJIT_USE_ASAN_HARDENING
#include <sanitizer/asan_interface.h>

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
static global_State *main_GS = NULL;

static int small_malloc_test(void *test_state)
{
#if !LUAJIT_USE_ASAN_HARDENING || LUAJIT_USE_SYSMALLOC
    UNUSED(test_state);
    return skip("Requires build with ASAN");
#else
    int res = -1;
    size_t size = 30;
    void *p = lj_mem_new(main_LS, size);
    size_t algn = (MALLOC_ALIGNMENT - size % MALLOC_ALIGNMENT) % MALLOC_ALIGNMENT;

    if (IS_POISONED_REGION(p - REDZONE_SIZE, REDZONE_SIZE) &&
        !IS_POISONED_REGION(p, size) &&
        IS_POISONED_REGION(p + size, algn + REDZONE_SIZE))
        res = TEST_EXIT_SUCCESS;

    lj_mem_free(main_GS, p, size);
	return res == TEST_EXIT_SUCCESS ? TEST_EXIT_SUCCESS : TEST_EXIT_FAILURE;
#endif
}

static int large_malloc_test(void *test_state)
{
#if !LUAJIT_USE_ASAN_HARDENING || LUAJIT_USE_SYSMALLOC
    UNUSED(test_state);
    return skip("Requires build with ASAN");
#else
    int res = -1;
    size_t size = 1234;
    void *p = lj_mem_new(main_LS, size);
    size_t algn = (MALLOC_ALIGNMENT - size % MALLOC_ALIGNMENT) % MALLOC_ALIGNMENT;

    if (IS_POISONED_REGION(p - REDZONE_SIZE, REDZONE_SIZE) &&
        !IS_POISONED_REGION(p, size) &&
        IS_POISONED_REGION(p + size, algn + REDZONE_SIZE))
        res = TEST_EXIT_SUCCESS;
        
    lj_mem_free(main_GS, p, size);
	return res == TEST_EXIT_SUCCESS ? TEST_EXIT_SUCCESS : TEST_EXIT_FAILURE;
#endif
}

static int free_test(void *test_state)
{
#if !LUAJIT_USE_ASAN_HARDENING || LUAJIT_USE_SYSMALLOC
    UNUSED(test_state);
    return skip("Requires build with ASAN");
#else
    size_t size = 1234;
    void *p = lj_mem_new(main_LS, size);
    size_t algn = (MALLOC_ALIGNMENT - size % MALLOC_ALIGNMENT) % MALLOC_ALIGNMENT;
    lj_mem_free(main_GS, p, size);

    if (IS_POISONED_REGION(p - REDZONE_SIZE, TOTAL_REDZONE_SIZE + size + algn))
    {
        return TEST_EXIT_SUCCESS;
    }
    return TEST_EXIT_FAILURE;
#endif
}

static int realloc_test(void *test_state)
{
#if !LUAJIT_USE_ASAN_HARDENING || LUAJIT_USE_SYSMALLOC
    UNUSED(test_state);
    return skip("Requires build with ASAN");
#else
    int res = -1;
    size_t size = 150;
    size_t new_size = size * 2;
    void *p = lj_mem_new(main_LS, size);
    uint8_t *ptr = (uint8_t *)p;
    size_t algn = (MALLOC_ALIGNMENT - size % MALLOC_ALIGNMENT) % MALLOC_ALIGNMENT;
    size_t new_algn = (MALLOC_ALIGNMENT - new_size % MALLOC_ALIGNMENT) % MALLOC_ALIGNMENT;

    for (size_t i = 0; i < size; ++i)
    {
        ptr[i] = i;
    }

    void *newptr = lj_mem_realloc(main_LS, p, size, new_size);

    if (IS_POISONED_REGION(ptr - REDZONE_SIZE, TOTAL_REDZONE_SIZE + size + algn))
    {
        ASAN_UNPOISON_MEMORY_REGION(ptr, size);
        if (memcmp(ptr, newptr, size) != 0)
            res = TEST_EXIT_FAILURE;

        if (IS_POISONED_REGION(newptr - REDZONE_SIZE, REDZONE_SIZE) &&
            !IS_POISONED_REGION(newptr, new_size) &&
            IS_POISONED_REGION(newptr + new_size, new_algn + REDZONE_SIZE))
            res = TEST_EXIT_SUCCESS;
    }
        lj_mem_free(main_GS, newptr, new_size);
	return res == TEST_EXIT_SUCCESS ? TEST_EXIT_SUCCESS : TEST_EXIT_FAILURE;
#endif
}

int main(void)
{
    lua_State *L = utils_lua_init();
    global_State *g = G(L);
    main_LS = L;
    main_GS = g;

    const struct test_unit tgroup[] = {
        test_unit_def(small_malloc_test),
        test_unit_def(large_malloc_test),
        test_unit_def(free_test),
        test_unit_def(realloc_test),
    };

    const int test_result = test_run_group(tgroup, L);
    utils_lua_close(L);
    return test_result;
}