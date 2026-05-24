#include <stdint.h>
#include <stdarg.h>

#define lengthof(a) (sizeof(a) / sizeof((a)[0]))

#define UNUSED(x) ((void)(x))

#if defined(__clang__)
#undef __GNUC__
#endif

struct sz12_t {
	float f1;
	float f2;
	float f3;
};

struct sz12_t retsz12(struct sz12_t a)
{
	return a;
}

struct sz12_t sum2sz12(struct sz12_t a, struct sz12_t b)
{
	struct sz12_t res = {0};
	res.f1 = a.f1 + b.f1;
	res.f2 = a.f2 + b.f2;
	res.f3 = a.f3 + b.f3;
	return res;
}

struct sz12_t sum3sz12(struct sz12_t a, struct sz12_t b, struct sz12_t c)
{
	struct sz12_t res = {0};
	res.f1 = a.f1 + b.f1 + c.f1;
	res.f2 = a.f2 + b.f2 + c.f2;
	res.f3 = a.f3 + b.f3 + c.f3;
	return res;
}

/****************************************************************/
/*                           Enums.                             */
/****************************************************************/

typedef enum {
	E1 = 1,
	E2 = 2,
	E3 = 3,
	E4 = 4,
	E5 = 5,
	E6 = 6,
	E7 = 7,
	E8 = 8,
	E9 = 9,
	E10 = 10,
	E11 = 11
} enum_t;

int test_enum_reg(enum_t e1, enum_t e2, enum_t e3)
{
	return e1 + e2 + e3;
}

int test_enum_stack(enum_t e1, enum_t e2, enum_t e3, enum_t e4, enum_t e5,
		    enum_t e6, enum_t e7, enum_t e8, enum_t e9, enum_t e10,
		    enum_t e11)
{
	return e1 + e2 + e3 + e4 + e5 + e6 + e7 + e8 + e9 + e10 + e11;
}

/****************************************************************/
/*                  Basic types (< 8 bytes).                    */
/****************************************************************/

uint8_t test_u8_stack(uint8_t u1, uint8_t u2, uint8_t u3, uint8_t u4,
		      uint8_t u5, uint8_t u6, uint8_t u7, uint8_t u8,
		      uint8_t u9, uint8_t u10, uint8_t u11)
{
	return u1 + u2 + u3 + u4 + u5 + u6 + u7 + u8 + u9 + u10 + u11;
}

float test_float_stack(float f1, float f2, float f3, float f4, float f5,
		       float f6, float f7, float f8, float f9, float f10,
		       float f11)
{
	return f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8 + f9 + f10 + f11;
}

/****************************************************************/
/*       Homogeneous Floating-Point Aggregate (HFA) argument.   */
/****************************************************************/

typedef struct hfa_float2 {
	float v[2];
} hfa_float2;

typedef union uhfa_float2 {
	float v[2];
} uhfa_float2;

typedef struct hfa_float22 {
	float v[2][2];
} hfa_float22;

typedef struct non_hfa_float222 {
	float v[2][2][2];
} non_hfa_float222;

typedef struct hfa_double2 {
	double v[2];
} hfa_double2;

typedef struct hfa_double2_a16 {
	__attribute__((__aligned__(16))) double v[2];
} hfa_double2_a16;

typedef struct hfa_double2_a32 {
	__attribute__((__aligned__(32))) double v[4];
} hfa_double2_a32;

float hfa_float2_sum(hfa_float2 h)
{
	return h.v[0] + h.v[1];
}

float uhfa_float2_sum(uhfa_float2 h)
{
	return h.v[0] + h.v[1];
}

float hfa_float22_sum(hfa_float22 h)
{
	return h.v[0][0] + h.v[0][1] + h.v[1][0] + h.v[1][1];
}

float non_hfa_float222_sum(non_hfa_float222 h)
{
	return h.v[0][0][0] + h.v[0][0][1] + h.v[0][1][0] + h.v[0][1][1] +
	       h.v[1][0][0] + h.v[1][0][1] + h.v[1][1][0] + h.v[1][1][1];
}

/*
 * Incorrect GCC behaviour.
 * See: https://gcc.gnu.org/bugzilla/show_bug.cgi?id=125023.
 */
#if !defined(__GNUC__)
typedef struct hfa_float_hole {
	float x;
	float hole[0][2][2];
	float y;
} hfa_float_hole;

float hfa_float_hole_sum(hfa_float_hole h)
{
	return h.x + h.y;
}
#endif /* GCC */

double hfa_double2_sum(hfa_double2 h)
{
	return h.v[0] + h.v[1];
}

double hfa_double2_a16_sum(hfa_double2_a16 h)
{
	return h.v[0] + h.v[1];
}

double hfa_double2_a32_sum(hfa_double2_a32 h)
{
	return h.v[0] + h.v[1] + h.v[2] + h.v[3];
}

/*
 * Enable only for GCC >= 12.0.0
 * See the first paragraph about the 0 bitfield:
 * https://gcc.gnu.org/gcc-12/changes.html.
 */
#if !defined(__GNUC__) || __GNUC__ >= 12
typedef struct hfa_0bitfield {
	float x;
	int : 0;
	float y;
	float z;
} hfa_0bitfield;

float hfa_0bitfield_sum(hfa_0bitfield h)
{
	return h.x + h.y + h.z;
}
#endif /* GNUC >= 12.0.0 */

/****************************************************************/
/*                     Empty structures.                        */
/****************************************************************/

struct empty {};

struct super_empty {
	int arr[0];
};

struct sort_of_empty {
	struct super_empty e;
};

struct empty empty_ret(void)
{
	struct empty e;
	return e;
}

struct super_empty super_empty_ret(void)
{
	struct super_empty e;
	return e;
}

struct sort_of_empty sort_of_empty_ret(void)
{
	struct sort_of_empty e;
	return e;
}

int empty_arg(struct empty e, int a)
{
	return a;
}

int super_empty_arg(struct super_empty e, int a)
{
	return a;
}

int sort_of_empty_arg(struct sort_of_empty e, int a)
{
	return a;
}

/****************************************************************/
/*                 Vector passing.                              */
/****************************************************************/

/* Test direct vector passing. */
typedef float vfloatx2 __attribute__ ((__vector_size__ (8)));
typedef float vfloatx4 __attribute__ ((__vector_size__ (16)));

/* Return the given value without change. */
vfloatx2  vfloatx2_call(vfloatx2 x) { return x; }
vfloatx4  vfloatx4_call(vfloatx4 x) { return x; }

typedef int int32x4_t __attribute__((__vector_size__ (4 * 4)));

int32x4_t test_hva_varg(int n, ...)
{
	va_list vl;
	va_start(vl, n);
	int32x4_t a = va_arg(vl, int32x4_t);
	int32x4_t b = va_arg(vl, int32x4_t);
	va_end(vl);
	int32x4_t res = a + b;
	return res;
}

/****************************************************************/
/*                Various argument types.                       */
/****************************************************************/

/* Testing alignment with aggregates. */

/*
 * HFA, aggregates with size <= 16 bytes and aggregates with
 * size > 16 bytes.
 */
typedef struct hfa_floatx4_a16 {
	float v[4];
} __attribute__((aligned(16))) hfa_floatx4_a16;

float test_2_align_hfa(int i, hfa_floatx4_a16 s1, hfa_floatx4_a16 s2)
{
	UNUSED(i);
	const float *v1 = s1.v;
	const float *v2 = s2.v;
	return v1[0] + v1[1] + v1[2] + v1[3] + v2[0] + v2[1] + v2[2] + v2[3];
}

/* Testing 16-byte aggregate. */
typedef struct intx4_a16 {
	int v[4];
} __attribute__((aligned(16))) intx4_a16;

int test_2_intx4_a16(int i, intx4_a16 s1, intx4_a16 s2)
{
	const int *v1 = s1.v;
	const int *v2 = s2.v;
	return i + v1[0] + v1[1] + v1[2] + v1[3] +
		   v2[0] + v2[1] + v2[2] + v2[3];
}

/* Testing large aggregate. */
typedef struct large_agg_a16 {
	int v[18];
} __attribute__((aligned(16))) large_agg_a16;

int test_2_large_agg_a16(int x, large_agg_a16 s1, large_agg_a16 s2)
{
	const int *v1 = s1.v;
	const int *v2 = s2.v;
	int sum = x;
	for (int i = 0; i < lengthof(s1.v); i++) {
		sum += v1[i] + v2[i];
	}
	return sum;
}

typedef struct intx3_0bitfield {
	int x;
	int : 0;
	int y;
	int z;
} intx3_0bitfield;

int test_2_intx3_0bitfield_reg(int i, intx3_0bitfield s1, intx3_0bitfield s2)
{
	return i + s1.x + s1.y + s1.z + s2.x + s2.y + s2.z;
}

int test_2_intx3_0bitfield_stack(int i, int i2, int i3, int i4, int i5, int i6,
				 int i7, int i8, int i9, intx3_0bitfield s1,
				 intx3_0bitfield s2)
{
	return i + s1.x + s1.y + s1.z + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 +
	       s2.x + s2.y + s2.z;
}

typedef struct intx3_0bitfield_a16 {
	int x;
	int : 0 __attribute__((aligned(16)));
	int y;
	int z;
} intx3_0bitfield_a16;

int test_2_intx3_0bitfield_a16_reg(int i, intx3_0bitfield_a16 s1,
				   intx3_0bitfield_a16 s2)
{
	return i + s1.x + s1.y + s1.z + s2.x + s2.y + s2.z;
}

int test_2_intx3_0bitfield_a16_stack(int i, int i2, int i3, int i4, int i5,
				     int i6, int i7, int i8, int i9,
				     intx3_0bitfield_a16 s1,
				     intx3_0bitfield_a16 s2)
{
	return i + s1.x + s1.y + s1.z + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 +
	       s2.x + s2.y + s2.z;
}

typedef struct intx3_full_bitfield_a16 {
	int x;
	int y: 32 __attribute__((aligned(16)));
	int z;
} intx3_full_bitfield_a16;

int test_2_intx3_full_bitfield_a16_reg(int i, intx3_full_bitfield_a16 s1,
				       intx3_full_bitfield_a16 s2)
{
	return i + s1.x + s1.y + s1.z + s2.x + s2.y + s2.z;
}

int test_2_intx3_full_bitfield_a16_stack(int i, int i2, int i3, int i4, int i5,
					 int i6, int i7, int i8, int i9,
					 intx3_full_bitfield_a16 s1,
					 intx3_full_bitfield_a16 s2)
{
	return i + s1.x + s1.y + s1.z + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 +
	       s2.x + s2.y + s2.z;
}

typedef struct intx3_half_bitfield {
	int x : 16;
	int y : 16;
	int z;
} intx3_half_bitfield;

int test_2_intx3_half_bitfield_reg(int i, intx3_half_bitfield s1,
				   intx3_half_bitfield s2)
{
	return i + s1.x + s1.y + s1.z + s2.x + s2.y + s2.z;
}

int test_2_intx3_half_bitfield_stack(int i, int i2, int i3, int i4, int i5,
				     int i6, int i7, int i8, int i9,
				     intx3_half_bitfield s1,
				     intx3_half_bitfield s2)
{
	return i + s1.x + s1.y + s1.z + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 +
	       s2.x + s2.y + s2.z;
}

typedef struct intx3_half_bitfield_a16 {
	int x : 16;
	int y : 16 __attribute__((aligned(16)));
	int z;
} intx3_half_bitfield_a16;

int test_2_intx3_half_bitfield_a16_reg(int i, intx3_half_bitfield_a16 s1,
				       intx3_half_bitfield_a16 s2)
{
	return i + s1.x + s1.y + s1.z + s2.x + s2.y + s2.z;
}

int test_2_intx3_half_bitfield_a16_stack(int i, int i2, int i3, int i4, int i5,
					 int i6, int i7, int i8, int i9,
					 intx3_half_bitfield_a16 s1,
					 intx3_half_bitfield_a16 s2)
{
	return i + s1.x + s1.y + s1.z + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 +
	       s2.x + s2.y + s2.z;
}

/* Increased natural alignment. */
typedef struct la16l {
	long long x __attribute__((aligned(16)));
	long long y;
} la16l;

int test_2_la16l_reg(int i, la16l s1, la16l s2)
{
	return s1.x + s2.x + i + s1.y + s2.y;
}

int test_2_la16l_stack(int i, int i2, int i3, int i4, int i5, int i6, int i7,
		       int i8, int i9, la16l s1, la16l s2)
{
	return s1.x + s2.x + i + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 + s1.y +
	       s2.y;
}

/****************************************************************/
/*                Transparent structures.                       */
/****************************************************************/

typedef struct a16_tsp {
	struct {
		long long x;
		long long y;
	} __attribute__((aligned(16)));
} a16_tsp;

int test_2_a16_tsp_reg(int i, a16_tsp s1, a16_tsp s2)
{
	return s1.x + s2.x + i + s1.y + s2.y;
}

int test_2_a16_tsp_stack(int i, int i2, int i3, int i4, int i5, int i6, int i7,
			 int i8, int i9, a16_tsp s1, a16_tsp s2)
{
	return s1.x + s2.x + i + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 + s1.y +
	       s2.y;
}

typedef struct f_a16_tsp {
	struct {
		long long x __attribute__((aligned(16)));
		long long y;
	};
} f_a16_tsp;

int test_2_f_a16_tsp_reg(int i, f_a16_tsp s1, f_a16_tsp s2)
{
	return s1.x + s2.x + i + s1.y + s2.y;
}

int test_2_f_a16_tsp_stack(int i, int i2, int i3, int i4, int i5, int i6,
			   int i7, int i8, int i9, f_a16_tsp s1, f_a16_tsp s2)
{
	return s1.x + s2.x + i + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 + s1.y +
	       s2.y;
}

/*
 * Test passing structs with size < 8, < 16 and > 16
 * with alignment of 16 and without.
 *
 * Structs with size <= 8 bytes, without alignment attribute
 * passed as i64 regardless of the align attribute.
 */
typedef struct is_no_align {
	int i;
	short s;
} is_no_align;

int test_2_is_no_align_reg(int i, is_no_align s1, is_no_align s2)
{
	return s1.i + s2.i + i + s1.s + s2.s;
}

int test_2_is_no_align_stack(int i, int i2, int i3, int i4, int i5, int i6,
			     int i7, int i8, int i9, is_no_align s1,
			     is_no_align s2)
{
	return s1.i + s2.i + i + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 + s1.s +
	       s2.s;
}

/* Structs with size <= 8 bytes, with alignment attribute. */
typedef struct is_a16 {
	int i;
	short s;
} __attribute__((aligned(16))) is_a16;

int test_2_is_a16_reg(int i, is_a16 s1, is_a16 s2)
{
	return s1.i + s2.i + i + s1.s + s2.s;
}

int test_2_is_a16_stack(int i, int i2, int i3, int i4, int i5, int i6, int i7,
			int i8, int i9, is_a16 s1, is_a16 s2)
{
	return s1.i + s2.i + i + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 + s1.s +
	       s2.s;
}

/* Structs with size <= 16 bytes, without alignment attribute. */
typedef struct isis_no_align {
	int i;
	short s;
	int i2;
	short s2;
} isis_no_align;

int test_2_isis_no_align_reg(int i, isis_no_align s1, isis_no_align s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + i + s1.s + s2.s + s1.s2 + s2.s2;
}

int test_2_isis_no_align_stack(int i, int i2, int i3, int i4, int i5, int i6,
			       int i7, int i8, int i9, isis_no_align s1,
			       isis_no_align s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + i + i2 + i3 + i4 + i5 + i6 + i7 +
	       i8 + i9 + s1.s + s2.s + s1.s2 + s2.s2;
}

/* Structs with size <= 16 bytes, with alignment attribute. */
typedef struct isis_a16 {
	int i;
	short s;
	int i2;
	short s2;
} __attribute__((aligned(16))) isis_a16;

int test_2_isis_a16_reg(int i, isis_a16 s1, isis_a16 s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + i + s1.s + s2.s + s1.s2 + s2.s2;
}

int test_2_isis_a16_stack(int i, int i2, int i3, int i4, int i5, int i6, int i7,
			  int i8, int i9, isis_a16 s1, isis_a16 s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + i + i2 + i3 + i4 + i5 + i6 + i7 +
	       i8 + i9 + s1.s + s2.s + s1.s2 + s2.s2;
}

/* structs with size > 16 bytes, without alignment attribute. */
typedef struct isisis {
	int i;
	short s;
	int i2;
	short s2;
	int i3;
	short s3;
} isisis_no_align;

int test_2_isisis_no_align_reg(int i, isisis_no_align s1, isisis_no_align s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + s1.i3 + s2.i3 + i + s1.s + s2.s +
	       s1.s2 + s2.s2 + s1.s3 + s2.s3;
}

int test_2_isisis_no_align_stack(int i, int i2, int i3, int i4, int i5, int i6,
				 int i7, int i8, int i9, isisis_no_align s1,
				 isisis_no_align s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + s1.i3 + s2.i3 + i + i2 + i3 + i4 +
	       i5 + i6 + i7 + i8 + i9 + s1.s + s2.s + s1.s2 + s2.s2 + s1.s3 +
	       s2.s3;
}

/* Structs with size > 16 bytes, with alignment attribute. */
typedef struct isisis_a16 {
	int i;
	short s;
	int i2;
	short s2;
	int i3;
	short s3;
} __attribute__((aligned(16))) isisis_a16;

int test_2_isisis_a16_reg(int i, isisis_a16 s1, isisis_a16 s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + s1.i3 + s2.i3 + i + s1.s + s2.s +
	       s1.s2 + s2.s2 + s1.s3 + s2.s3;
}

int test_2_isisis_a16_stack(int i, int i2, int i3, int i4, int i5, int i6,
			    int i7, int i8, int i9, isisis_a16 s1,
			    isisis_a16 s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + s1.i3 + s2.i3 + i + i2 + i3 + i4 +
	       i5 + i6 + i7 + i8 + i9 + s1.s + s2.s + s1.s2 + s2.s2 + s1.s3 +
	       s2.s3;
}

/* We should not split struct argument between regs and stack. */
int test_2_isis_no_align_split(int i, int i2, int i3, int i4, int i5, int i6,
			       int i7, isis_no_align s1, isis_no_align s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + i + i2 + i3 + i4 + i5 + i6 + i7 +
	       s1.s + s2.s + s1.s2 + s2.s2;
}

int test_2_isis_a16_split(int i, int i2, int i3, int i4, int i5, int i6, int i7,
			  isis_a16 s1, isis_a16 s2)
{
	return s1.i + s2.i + s1.i2 + s2.i2 + i + i2 + i3 + i4 + i5 + i6 + i7 +
	       s1.s + s2.s + s1.s2 + s2.s2;
}

/****************************************************************/
/*                Packed structures.                            */
/****************************************************************/

typedef struct ill_packed {
	int x;
	long long y;
} __attribute__((packed)) ill_packed;

typedef struct ii {
	int x;
	int y;
} ii;

/* Passing structs with unaligned fields, not in registers. */
int test_2_ill_packed(int i, ill_packed s1, ill_packed s2)
{
	return s1.x + s2.x + i + s1.y + s2.y;
}

int test_2_ill_packed_reord(int i, ill_packed s1, ill_packed s2, int i2, ii s3)
{
	return s1.x + s2.x + i + s1.y + s2.y + i2 + s3.x + s3.y;
}

int test_2_ill_packed_stack(int i, int i2, int i3, int i4, int i5, int i6,
			    int i7, int i8, int i9, ill_packed s1,
			    ill_packed s2)
{
	return s1.x + s2.x + i + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 + s1.y +
	       s2.y;
}

/* Packed structure, overaligned, same as above. */
typedef struct ill_packed_a16 {
	int x;
	long long y;
} __attribute__((packed, aligned(16))) ill_packed_a16;

/* Passing structs with unaligned fields not in registers. */
int test_2_ill_packed_a16(int i, ill_packed_a16 s1, ill_packed_a16 s2)
{
	return s1.x + s2.x + i + s1.y + s2.y;
}

int test_2_ill_packed_a16_reord(int i, ill_packed_a16 s1, ill_packed_a16 s2,
				int i2, ii s3)
{
	return s1.x + s2.x + i + s1.y + s2.y + i2 + s3.x + s3.y;
}

int test_2_ill_packed_a16_stack(int i, int i2, int i3, int i4, int i5, int i6,
				int i7, int i8, int i9, ill_packed_a16 s1,
				ill_packed_a16 s2)
{
	return s1.x + s2.x + i + i2 + i3 + i4 + i5 + i6 + i7 + i8 + i9 + s1.y +
	       s2.y;
}
