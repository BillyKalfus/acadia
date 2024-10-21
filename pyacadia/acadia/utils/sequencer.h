#ifndef SEQUENCER_H
#define SEQUENCER_H

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

void sequencer_halt_and_reset(volatile uint32_t*);
void sequencer_run(volatile uint32_t*);
uint8_t sequencer_done(volatile uint32_t*);
void sequencer_complete(volatile uint32_t*);
void sequencer_mem_barrier(volatile uint32_t*);

#endif