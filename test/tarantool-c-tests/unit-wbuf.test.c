/*
** Testing of the write buffer.
**
** The write buffer accumulates the profilers' output and passes
** it to the writer on flush. The tests below cover writing of the
** data of all kinds, flushing on overflow, the explicit flush and
** the error reporting.
*/

#include <errno.h>

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "lj_wbuf.h"
#include "test.h"

/* Size of the write buffer used in the tests. */
#define BUFFER_SIZE 10

/* Size of the payload that does not fit into the write buffer. */
#define PAYLOAD_SIZE (2 * BUFFER_SIZE + 5)

/* What the writer does on flush. */
enum writer_mode {
	/* Report all the data as written. */
	WMODE_OK,
	/* Report a half of the data as written and keep the buffer. */
	WMODE_PARTIAL,
	/* Imitate an unrecoverable write error, e.g. ENOSPC. */
	WMODE_FAIL,
};

/* Writer context for simulating different write outcomes. */
struct writer_ctx {
	/* What the writer does on flush. */
	enum writer_mode mode;
	/* Number of performed flushes. */
	size_t flushes;
	/* Number of bytes reported as written. */
	size_t written;
	/* Everything reported as written, in order of writing. */
	uint8_t out[2 * PAYLOAD_SIZE];
};

static size_t test_writer(const void **buf_addr, size_t len, void *opt)
{
	struct writer_ctx *ctx = opt;
	size_t n = len;

	ctx->flushes++;
	if (ctx->mode == WMODE_FAIL) {
		errno = ENOSPC;
		*buf_addr = NULL;
		return 0;
	}
	if (ctx->mode == WMODE_PARTIAL) {
		errno = EIO;
		n = len / 2;
	}
	memcpy(ctx->out + ctx->written, *buf_addr, n);
	ctx->written += n;
	return n;
}

static void writer_ctx_init(struct writer_ctx *ctx, enum writer_mode mode)
{
	memset(ctx, 0, sizeof(*ctx));
	ctx->mode = mode;
}

static size_t buf_len(const struct lj_wbuf *buf)
{
	return (size_t)(buf->pos - buf->buf);
}

static void assert_stream_stopped_with_error(const struct lj_wbuf *buf)
{
	assert_true(lj_wbuf_test_flag(buf, STREAM_STOP));
	assert_true(lj_wbuf_test_flag(buf, STREAM_ERRIO));
	assert_int_equal(lj_wbuf_errno(buf), ENOSPC);
	assert_ptr_equal(buf->buf, NULL);
	assert_ptr_equal(buf->pos, NULL);
}

static int test_addbyte(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	lj_wbuf_addbyte(&buf, 0x7f);
	assert_sizet_equal(buf_len(&buf), 1);
	assert_int_equal(mem[0], 0x7f);
	assert_sizet_equal(ctx.flushes, 0);
	assert_int_equal(lj_wbuf_errno(&buf), 0);

	return TEST_EXIT_SUCCESS;
}

static int test_addu64(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/* 128 is encoded as two bytes. */
	lj_wbuf_addu64(&buf, 128);
	assert_sizet_equal(buf_len(&buf), 2);
	assert_int_equal(mem[0], 0x80);
	assert_int_equal(mem[1], 0x01);
	assert_sizet_equal(ctx.flushes, 0);

	return TEST_EXIT_SUCCESS;
}

static int test_addn(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	lj_wbuf_addn(&buf, "xyz", 3);
	assert_sizet_equal(buf_len(&buf), 3);
	assert_true(memcmp(mem, "xyz", 3) == 0);
	assert_sizet_equal(ctx.flushes, 0);

	return TEST_EXIT_SUCCESS;
}

static int test_addstring(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/* A string is a ULEB128 length followed by the payload. */
	lj_wbuf_addstring(&buf, "xyz");
	assert_sizet_equal(buf_len(&buf), 4);
	assert_int_equal(mem[0], 3);
	assert_true(memcmp(mem + 1, "xyz", 3) == 0);
	assert_sizet_equal(ctx.flushes, 0);

	return TEST_EXIT_SUCCESS;
}

static int test_addn_pumped_through_buffer(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	uint8_t payload[PAYLOAD_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	memset(payload, 'a', sizeof(payload));
	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/*
	 * The payload does not fit into the buffer, so it is
	 * pumped through it. Two full buffers are flushed, the
	 * rest stays in the buffer.
	 */
	lj_wbuf_addn(&buf, payload, sizeof(payload));
	assert_sizet_equal(ctx.flushes, 2);
	assert_sizet_equal(ctx.written, 2 * BUFFER_SIZE);
	assert_true(memcmp(ctx.out, payload, 2 * BUFFER_SIZE) == 0);
	assert_sizet_equal(buf_len(&buf), PAYLOAD_SIZE - 2 * BUFFER_SIZE);
	assert_true(memcmp(mem, payload + 2 * BUFFER_SIZE,
			   PAYLOAD_SIZE - 2 * BUFFER_SIZE) == 0);

	return TEST_EXIT_SUCCESS;
}

static int test_flush_on_overflow(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	uint8_t payload[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	memset(payload, 'a', sizeof(payload));
	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/* A byte written to a full buffer is preceded by a flush. */
	lj_wbuf_addn(&buf, payload, sizeof(payload));
	assert_sizet_equal(buf_len(&buf), sizeof(mem));
	lj_wbuf_addbyte(&buf, 0xaa);
	assert_sizet_equal(ctx.flushes, 1);
	assert_sizet_equal(ctx.written, sizeof(mem));
	assert_sizet_equal(buf_len(&buf), 1);
	assert_int_equal(mem[0], 0xaa);

	/* The same for an ULEB128 value written to a full buffer. */
	lj_wbuf_addn(&buf, payload, sizeof(payload) - 1);
	assert_sizet_equal(buf_len(&buf), sizeof(mem));
	lj_wbuf_addu64(&buf, 0);
	assert_sizet_equal(ctx.flushes, 2);
	assert_sizet_equal(ctx.written, 2 * sizeof(mem));
	assert_sizet_equal(buf_len(&buf), 1);

	/* And for a data block written to a full buffer. */
	lj_wbuf_addn(&buf, payload, sizeof(payload) - 1);
	assert_sizet_equal(buf_len(&buf), sizeof(mem));
	lj_wbuf_addn(&buf, payload, 1);
	assert_sizet_equal(ctx.flushes, 3);
	assert_sizet_equal(ctx.written, 3 * sizeof(mem));
	assert_sizet_equal(buf_len(&buf), 1);

	return TEST_EXIT_SUCCESS;
}

static int test_flush(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	lj_wbuf_addn(&buf, "xyz", 3);
	lj_wbuf_flush(&buf);
	assert_sizet_equal(ctx.flushes, 1);
	assert_sizet_equal(ctx.written, 3);
	assert_true(memcmp(ctx.out, "xyz", 3) == 0);
	/* The buffer is empty after a successful flush. */
	assert_sizet_equal(buf_len(&buf), 0);
	assert_false(lj_wbuf_test_flag(&buf, STREAM_ERRIO | STREAM_STOP));

	/* The buffer is usable after the flush. */
	lj_wbuf_addbyte(&buf, 0x7f);
	assert_sizet_equal(buf_len(&buf), 1);
	assert_int_equal(mem[0], 0x7f);

	return TEST_EXIT_SUCCESS;
}

static int test_flush_partial_write(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_PARTIAL);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	lj_wbuf_addn(&buf, "xyz", 3);
	lj_wbuf_flush(&buf);
	/* A partial write is reported as an error. */
	assert_true(lj_wbuf_test_flag(&buf, STREAM_ERRIO));
	assert_int_equal(lj_wbuf_errno(&buf), EIO);
	/* The writer keeps the buffer, so the stream is not stopped. */
	assert_false(lj_wbuf_test_flag(&buf, STREAM_STOP));
	assert_ptr_equal(buf.buf, mem);
	/* The unwritten data is dropped. */
	assert_sizet_equal(buf_len(&buf), 0);

	return TEST_EXIT_SUCCESS;
}

static int test_flush_stopped_stream(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_FAIL);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	lj_wbuf_addn(&buf, "xyz", 3);
	lj_wbuf_flush(&buf);
	assert_stream_stopped_with_error(&buf);
	assert_sizet_equal(ctx.flushes, 1);

	/* A stopped stream is not flushed again. */
	lj_wbuf_flush(&buf);
	assert_sizet_equal(ctx.flushes, 1);

	return TEST_EXIT_SUCCESS;
}

static int test_write_to_stopped_stream(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_FAIL);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	lj_wbuf_addn(&buf, "xyz", 3);
	lj_wbuf_flush(&buf);
	assert_stream_stopped_with_error(&buf);

	/* Writes to a stopped stream are ignored. */
	lj_wbuf_addbyte(&buf, 0x7f);
	lj_wbuf_addu64(&buf, 128);
	lj_wbuf_addn(&buf, "xyz", 3);
	lj_wbuf_addstring(&buf, "xyz");
	assert_stream_stopped_with_error(&buf);
	assert_sizet_equal(ctx.flushes, 1);
	assert_sizet_equal(ctx.written, 0);

	return TEST_EXIT_SUCCESS;
}

static int test_terminate(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_OK);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	lj_wbuf_terminate(&buf);
	assert_true(buf.writer == NULL);
	assert_ptr_equal(buf.ctx, NULL);
	assert_ptr_equal(buf.buf, NULL);
	assert_ptr_equal(buf.pos, NULL);
	assert_sizet_equal(buf.size, 0);
	assert_false(lj_wbuf_test_flag(&buf, STREAM_ERRIO | STREAM_STOP));
	assert_int_equal(lj_wbuf_errno(&buf), 0);

	return TEST_EXIT_SUCCESS;
}

/*
** A writer may release the buffer and set *data to NULL on an
** unrecoverable error (e.g. ENOSPC). The stream is stopped in
** this case, so the write functions must not touch the released
** buffer.
*/
static int test_addbyte_failed_flush(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;
	size_t i;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_FAIL);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/* Fill the buffer without flushes. */
	for (i = 0; i < sizeof(mem); ++i)
		lj_wbuf_addbyte(&buf, (uint8_t)i);
	assert_sizet_equal(ctx.flushes, 0);
	assert_sizet_equal(buf_len(&buf), sizeof(mem));

	/* The buffer is full, so the byte below triggers a failed flush. */
	lj_wbuf_addbyte(&buf, 0xaa);
	assert_stream_stopped_with_error(&buf);
	assert_sizet_equal(ctx.flushes, 1);

	return TEST_EXIT_SUCCESS;
}

static int test_addu64_failed_flush(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	writer_ctx_init(&ctx, WMODE_FAIL);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/* The maximal value takes exactly BUFFER_SIZE bytes. */
	lj_wbuf_addu64(&buf, UINT64_MAX);
	assert_sizet_equal(buf_len(&buf), sizeof(mem));

	/* There is no space left, so the next write triggers a failed flush. */
	lj_wbuf_addu64(&buf, 0);
	assert_stream_stopped_with_error(&buf);
	assert_sizet_equal(ctx.flushes, 1);

	return TEST_EXIT_SUCCESS;
}

static int test_addn_failed_flush(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	uint8_t payload[BUFFER_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	memset(payload, 'a', sizeof(payload));
	writer_ctx_init(&ctx, WMODE_FAIL);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/* Fill the buffer without flushes. */
	lj_wbuf_addn(&buf, payload, sizeof(payload));
	assert_sizet_equal(ctx.flushes, 0);

	/* There is no space left, so the next write triggers a failed flush. */
	lj_wbuf_addn(&buf, "b", 1);
	assert_stream_stopped_with_error(&buf);
	assert_sizet_equal(ctx.flushes, 1);

	return TEST_EXIT_SUCCESS;
}

static int test_addn_failed_flush_in_loop(void *state)
{
	uint8_t mem[BUFFER_SIZE];
	uint8_t payload[PAYLOAD_SIZE];
	struct lj_wbuf buf;
	struct writer_ctx ctx;

	UNUSED(state);

	memset(payload, 'a', sizeof(payload));
	writer_ctx_init(&ctx, WMODE_FAIL);
	lj_wbuf_init(&buf, test_writer, &ctx, mem, sizeof(mem));

	/*
	 * The payload does not fit into the buffer, so it is pumped through
	 * it. The flush fails in the middle of the pump loop.
	 */
	lj_wbuf_addn(&buf, payload, sizeof(payload));
	assert_stream_stopped_with_error(&buf);
	assert_sizet_equal(ctx.flushes, 1);

	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	const struct test_unit tgroup[] = {
		test_unit_def(test_addbyte),
		test_unit_def(test_addu64),
		test_unit_def(test_addn),
		test_unit_def(test_addstring),
		test_unit_def(test_addn_pumped_through_buffer),
		test_unit_def(test_flush_on_overflow),
		test_unit_def(test_flush),
		test_unit_def(test_flush_partial_write),
		test_unit_def(test_flush_stopped_stream),
		test_unit_def(test_write_to_stopped_stream),
		test_unit_def(test_terminate),
		test_unit_def(test_addbyte_failed_flush),
		test_unit_def(test_addu64_failed_flush),
		test_unit_def(test_addn_failed_flush),
		test_unit_def(test_addn_failed_flush_in_loop),
	};
	const int test_result = test_run_group(tgroup, NULL);

	return test_result;
}
