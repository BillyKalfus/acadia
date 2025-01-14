#ifndef SYSTEM_TIMER_H
#define SYSTEM_TIMER_H

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>

uint64_t clock_monotonic_ns(void);
uint64_t clock_monotonic_raw_ns(void);
int sys_nanosleep(uint64_t);

#endif