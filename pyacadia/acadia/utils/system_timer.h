#ifndef SYSTEM_TIMER_H
#define SYSTEM_TIMER_H

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

void timer_enable(volatile uint32_t* mem, int en);
uint64_t timer_value(volatile uint32_t*);
uint32_t timer_frequency(volatile uint32_t*);

#endif