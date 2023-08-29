#include <stdint.h>

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
