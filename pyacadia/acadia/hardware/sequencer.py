"""
sequencer.py
A set of Symbols for programming the Acadia sequencer.
William Kalfus, Yale University
September 2022
"""
from acadia.assembler import Symbol

REG         = Symbol(0) # Source and Destination
PC          = Symbol(8) # Source and Destination
IMM         = Symbol(9) # Source
HOLD        = Symbol(9) # Destination
TEST_VAL    = Symbol(10) # Source
BRANCH_MASK = Symbol(10) # Destination
FLAGS       = Symbol(11) # Source and Destination
STACK       = Symbol(12) # Source and Destination
BUS_ADDR    = Symbol(13) # Source and Destination
BUS_DATA    = Symbol(14) # Source and Destination
BUS_PEEK    = Symbol(15) # Source
ALU_OUT_LO  = Symbol(16) # Source
ALU_SEL     = Symbol(16) # Destination
ALU_OUT_HI  = Symbol(17) # Source
ALU_A       = Symbol(17) # Destination
ALU_B       = Symbol(18) # Destination
TC_RUN      = Symbol(19) # Destination
TC          = Symbol(24) # Source and Destination
TCS         = Symbol(28) # Source
TCC         = Symbol(28) # Destination
    