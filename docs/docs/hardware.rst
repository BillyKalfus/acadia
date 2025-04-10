====================
Hardware Description
====================


System Overview
=================

The instrument is internally divided into three sections: 

* The Programmable Logic (PL), which is a large region of FPGA fabric tightly coupled to both the PS and the RF tiles. 

* The RF tiles, which are groups of high-speed analog-to-digital converters (ADCs) and digital-to-analog converters (DACs). The grouping into tiles allows some converters to share resources, such as clocking. 

* The Processor Subsystem (PS), which is a cluster of four ARM Cortex-A53 processors capable of running Linux or bare-metal application code.

The following sections will describe each of these components in further detail.

Logic Design
==============

Sequencer
-----------

The sequencer is a small real-time CPU that is responsible for coordinating actions across the system. It steps through a sequence of instructions, each of which moves data from one location in the internal datapath of the sequencer (the "sources") to another (the "destinations"). All source and destination ports are 32 bits wide.

When the sequencer starts, it begins stepping through instruction memory and executing instructions in order. The sequencer has only one instruction, which can specify the following operations 

* Retrieve values from any two source ports and write them into any two destination ports, independently of one another

* Retrieve a value from one source and conditionally write it to one destination, conditioned on the value of an operation on a second source

Many destination ports will take additional action when written to or provide access to logic units that carry out more complex operations, described in further detail below. This architecture greatly reduces the critical path of the sequencer, allowing the clock speed to remain reasonably high while allowing the sequencer to fetch and execute instructions with low latency. This behavior is extremely useful for distributed systems requiring a high degree of synchronicity, since this means that the sequencer is able to operate at the finest timebase resolution of the system. 

In each instruction, two source ports (denoted src1 and src2) are always read. A bitwise operation (specified by the instruction) is computed between the value of src2 and the value of a special-purpose register referred to as the "mask". The complete list of available operations are listed in :ref:`Machine Code Reference`. The result of this operation may optionally be used as the value of src1. For conditional writes, the result of the operation is always used as the test condition; the condition is said to "pass" if the value is non-zero (this behavior may be inverted by setting the COND_INV bit in the instruction). 

The sequencer's execution consists of sequentially fetching instructions from instruction memory and executing each one. One instruction is fetched and executed every cycle, and a pointer to the instruction currently being fetched is maintained in a register called the Program Counter (PC). The instruction memory has a two-stage pipeline at its output, so the address of an instruction being executed will have occupied the PC two cycles prior.

The PC is both a source and a destination, which allows both relative and absolute branching to be performed. Conditional branching is implemented via a conditional write to the PC. When the PC is written to by an instruction, the sequencer will stall for two cycles to account for the fetch pipeline, and then execute the instruction at the address now contained in the PC. Otherwise, the PC is automatically incremented each cycle. 

The sequencer embeds eight 32-bit general-purpose registers in its datapath. In a single cycle, any two registers may be read from and/or any two registers may be written to, completely independently of one another. When reading from a register, the source multiplexer allows the register to be read as a full 32-bit value or as a concatenation of two 16-bit values (which are then zero-extended to 32 bits). This allows efficient packing of data when exclusively small values are needed. Because these two 16-bit registers are aliases for the upper and lower words of a register, writing to the register will affect the value read from both 16-bit aliases.

The sequencer also embeds eight DSP slices in its datapath, which may be used to compute various arithmetic operations. The DSP slice has two input registers (called "AB" and "C"), a result register (called "P"), and a configuration register; all but the configuration register may be used as inputs in the operation carried out by the slice, along with the P register of the neighboring slice. Each DSP slice also has an "enable" signal; when the enable signal is driven high, the the operation specified in the configuration register is carried out and stored into P. The enable signal may be set high indefinitely, cleared indefinitely, or pulsed for one cycle when writing to the configuration register. The enable signal may also be pulsed during any instruction by setting the appropriate bitfield, as shown in :ref:`Machine Code Reference`. Setting the enable signal high indefinitely allows the operation to be recomputed each cycle without intervention from the sequencer; since the P register can be an input to the operation, this allows one to implement operations that automatically update, such as a self-incrementing counter. The AB and C registers are exposed to the sequencer as destination ports, and P is exposed as a source port (after passing through a single-stage pipeline delay).

An eight-deep stack is also embedded in the sequencer datapath. Writing to the stack destination "pushes" a new value to its top, and reading from its source "pops" a value from the top. Writing to a full stack has no effect, and reading from an empty stack produces undefined data.

The sequencer communicates with external peripherals through the use of a 32-bit bidirectional data bus. The bus is addressed by writing a value to the "bus address" destination. A write command may then issued to the bus by writing to the "bus data" destination, or a read command may be issued by reading from the "bus data" source.

Machine Code Reference
^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table:: Instruction format
   :widths: 20 20 60
   :header-rows: 1

   * - Bits
     - Field Name
     - Description
   * - 127-113
     -
     - Reserved
   * - 112
     - COND 
     - When this bit is set, the instruction is interpreted as a conditional write; otherwise, it performs two concurrent writes.
   * - 111-105
     - 
     - Reserved
   * - 104
     - PUSH_RETURN
     - When this bit is set, the value of the Program Counter minus 1 is pushed to the stack. Note that if the instruction specifies the stack as a destination, then that transfer will override this bit.
   * - 103-96
     - SRC1
     - For conditional writes, this source will be used to retrieve the value that will be written if the condition passes. For unconditional writes, this source will be used to retrieve the value that will be written to the destination specified by DEST1.
   * - 95-88
     - SRC2
     - For conditional writes, this source will be used to retrieve the value that will be tested in order to compute the condition. For unconditional writes, this source will be used to retrieve the value that will be written to the destination specified by DEST2.
   * - 87-80
     - DEST1
     - Specifies the destination to which the value from SRC1 will be written in unconditional writes, or in conditional writes when the condition passes. 
   * - 79-72
     - DEST2
     - Specifies the destination to which the value from SRC2 will be written in unconditional writes. This is unused in conditional writes.
   * - 71
     - COND_INV
     - For conditional writes, the condition flag is inverted; in other words, when this bit is cleared, the condition passes when the result of the operation between SRC2 and the mask is nonzero. When this bit is set, the condition passes when it is equal to zero.
   * - 70-68
     - OP_SEL
     - Specifies the operation acting on SRC2.
   * - 67
     - DSP_CEP_EN
     - When this bit is set, the DSP slice specified by the value of the DSP_CEP field will have its enable signal pulsed.
   * - 66-64
     - DSP_CEP
     - Specifies which DSP will have its enable signal pulsed if DSP_CEP_EN is set high.
   * - 63-32
     - IMM1
     - An immediate value which may be used for SRC1.
   * - 31-0
     - IMM2
     - An immediate value which may be used for SRC2.

.. list-table:: Values for SRC1/SRC2
   :widths: 20 20 60
   :header-rows: 1

   * - SRCx[7:3]
     - Name
     - Description
   * - 0000
     - REG
     - The 32-bit values stored in a register specified by SRCx[2:0].
   * - 0001
     - REG_LO
     - The lower 16 bits of the register specified by SRC[2:0]. The upper 16 bits are set to zero.
   * - 0010
     - REG_HI
     - The upper 16 bits of the register specified by SRC[2:0]. These 16 bits are shifted down to occupy the lower 16 bits of the data to be written, and the upper 16 bits are set to zero.
   * - 0011
     - OP
     - The result of the bitwise operation between SRC2 and the mask.
   * - 0100
     - PC
     - Program counter
   * - 0101
     - IMM
     - For SRC1, this yields the IMM1 field of the instruction. For SRC2, this yields the IMM2 field of the instruction.
   * - 0110
     - EXT
     - External digital signals.
   * - 0111
     - STACK
     - A value is popped from the stack.
   * - 1000
     - BUS_DATA
     - The data at the read port of the bus.
   * - 1001 
     - 
     - Reserved
   * - 1010
     - DSP_P
     - The value of the P register for a DSP slice. The DSP slice to be read is specified by SRCx[2:0]
   * - others
     - 0
     - zero

.. list-table:: Values for DEST1/DEST2
   :widths: 20 20 60
   :header-rows: 1

   * - DESTx[7:3]
     - Name
     - Description
   * - 0000
     - None
     - No write is performed.
   * - 0001
     - REG
     - The 32-bit register specified by DESTx[2:0].
   * - 0010
     - PC
     - The program counter. Note that writing to this destination will force the sequencer to stall for two cycles.
   * - 0011
     - MASK
     - The mask register, to be used as the second operand for bitwise operations with src2.
   * - 0100
     - EXT
     - External digital signals
   * - 0101
     - STACK
     - Push to the stack
   * - 0110
     - BUS_DATA
     - Issues a write command on the bus to the address stored in the bus address register.
   * - 0111
     - BUS_ADDR
     - The bus address register
   * - 1000
     - DSP_CFG
     - The configuration register for the DSP slice specified by DESTx[2:0].
   * - 1001 
     - DSP_AB
     - The AB register for the DSP slice specified by DESTx[2:0].
   * - 1010
     - DSP_C
     - The C register for the DSP slice specified by DESTx[2:0].
   * - others
     - None
     - No effect

.. list-table:: OP_SEL behavior
   :widths: 25 25 50
   :header-rows: 1

   * - OP_SEL
     - Operation
     - Notes / Use cases
   * - 000
     - SRC2
     - No additional operation / modification
   * - 001
     - not SRC2
     - Bitwise inversion
   * - 010
     - SRC2 XOR mask
     - When COND_INV = 1, the condition will pass when SRC2 = MASK
   * - 011
     - (not SRC2) XOR mask
     - 
   * - 100
     - SRC2 AND mask
     - When COND_INV = 0, the condition will pass when any bits that are set in the mask are also set in SRC2, ignoring any additional bits in SRC2 which may be set.
   * - 101
     - (not SRC2) AND mask
     - When COND_INV = 1, the condition will pass when all bits that are set in the mask are also set in SRC, ignoring any additional bits in SRC which may be set
   * - others
     - undefined
     - Undefined behavior; do not use.


Memory and Communication Infrastructure
-----------------------------------------

Cache Memory
^^^^^^^^^^^^^^

Sequencer Instruction Memory
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Sequencer AXI Crossbar
^^^^^^^^^^^^^^^^^^^^^^^^

Bulk Memory AXI Interconnect
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Signal Synthesis, Capture, and Processing
-------------------------------------------

ADC AXI-Stream Switch
^^^^^^^^^^^^^^^^^^^^^^^

Real-Time Direct Memory Access (DMA) Modules
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

\begin{longtable} {@{}||c|>{\raggedright}p{2.5cm}|p{10cm}||@{}}
  \hline
  Bits & Field Name & Description \\ 
  \hline\hline
  \endfirsthead
  
  \hline
  Bits & Field Name & Description \\ 
  \hline\hline
  \endhead
  
  \hline
  \endfoot
  
  \hline
  \endlastfoot
  
  31-0 & LM1 & One less than the length of the trace to be played. \\ \hline
  47-32 & ADDR & The address exposed to the HEDGEHOG logic for this descriptor. \\ \hline
  55-48 & DECIMATE & A factor by which to decimate the stream. \\ \hline
  56 & BLANK & When 1, the memory reset signal will be asserted during the descriptor.\\ \hline
  57 & FIXED & When 1, the address output will not increment during the descriptor.\\ \hline
  63-58 & Reserved & These bits are reserved and will be ignored. \\ \hline
  % 47-44 & DEST & The value exposed on the TDEST port of the AXI-Stream address interface. \\ \hline
  % 63-48 & USER & The value exposed on the TUSER port of the AXI-Stream address interface. \\ \hline
  
\end{longtable}

ADC Sample FIFOs
^^^^^^^^^^^^^^^^^^

Complex Multiplier with Accumulator (CMACC)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Complex Multiplier and Accumulator (CMACC) module provides a low-latency solution for measuring the vector amplitude of captured signals in real time. Each sample that enters the CMACC is multiplied with the corresponding sample of a complex window/kernel, and the result is iteratively summed ("accumulated") in a register (the "accumulator"). By choosing an appropriate window function, different bands of noise can be rejected from the incoming signal. This architecture can also allow the signal to be processed with a matched filter, which optimizes the noise rejection when trying to distinguish between two discrete vector amplitudes.

Each CMACC has a dedicated bank of window function memory with a depth of 2048 samples. Before streaming a signal into the CMACC, the sequencer is expected to write an address in window function memory into the corresponding CMACC register, to be interpreted by the CMACC as a pointer to the start of the window function. An internal counter increments each cycle as samples enter the CMACC, and its value is added to the provided memory pointer in order to retrieve the appropriate window function sample for that point in time. The sequencer must also provide a length, and when the counter reaches this length, it is reset. This enables the use of periodic window functions that are much longer than the depth of the window function memory. A special case of this is the commonly-used "boxcar" window, which only requires loading a single entry in window memory.

The primary datapath of the CMACC is as follows:

1. Four samples enter the CMACC, each comprised of two 16-bit signed quadratures.

1. The four input samples are summed together, yielding a complex value with 18-bit signed quadratures.

1. The partial products of the complex multiplication between the input signal and the kernel are calculated as four 34-bit signed numbers, resulting from the product of the 18-bit summed input sample quadratures and the 16-bit window function sample quadratures.

1. The partial products are sign-extended to 48 bits and added into 48-bit accumulators for each quadrature.

When a set of samples enters the CMACC with the ``last`` flag set, once they have been multiplied and incorporated into the accumulator, the internal registers of the CMACC module will set a ``done`` signal. The sequencer may monitor this signal over the bus in order to determine when the capture is complete. The sequencer can then choose to read the upper 32 bits of the accumulator quadartures. In principle, the sequencer may read the value of the accumulator during the accumulation, but the value will change each cycle; observing the ``done`` signal allows the sequencer to be certain that the accumulator value will be stable until the next signal enters the CMACC. The ``done`` signal is purely for the user's convenience, and may be set or reset at any time by writing to the CMACC configuration register.

The CMACC has an output stream port that can produce a single complex value with two 32-bit quadratures each cycle. A multiplexer preceding the output port allows the user to choose whether the 18-bit summed input signal, the upper 32 bits of the accumulator, the lower 32 bits of the accumulator, or nothing is streamed out of the output port. Additionally, the user can choose whether only the last value is written to the output port, or whether an output is produced for every valid output entering the CMACC. Common configurations for these settings include bypassing the accumulator entirely and duplicating the input signal at the output, or writing only the final accumulated value to the output.

AXI DataMovers
^^^^^^^^^^^^^^^^

RF Data Converters
====================

The RF Data Converter subsystem of the RFSoC comprises a variety of digital signal processing hardware in addition to the actual data conversion cores themselves. The existence and performance of these modules is a critical benefit of using the RFSoC, and we now describe a subset of these features employed in Acadia.

Digital-to-Analog Converters (DAC)
------------------------------------

The DAC region of the RF Data Converter tile embedded in the RFSoC contains much more than simply a DAC core; notably, a chain of pre-processing logic preceding the DAC core and a highly-connected clock synthesis and distribution network for the sample clock, both of which are reconfigurable in software. We'll describe the various features of the components integrated in the hardware below. 

Gearbox FIFO
^^^^^^^^^^^^^^

Samples are provided to the DAC via a first-in-first-out (FIFO) queue. The FIFOs are reconfigurable and may be configured for various different throughputs depending on the programmed sampling rate of the DAC, the clock frequency of the logic feeding it, and any interpolation (described below). In the default firmware configuration, every DAC is configured to accept four samples per clock cycle, each of which is comprised of two 16-bit quadratures. The quadrature values are expressed as two's-complement signed numbers; correspondingly, the maximum positive number is 2^15 - 1 and the minimum negative number is -2^15. Note that this asymmetry restricts the valid full-scale values to a range of [-1,1), where the open interval on the right corresponds to an offset of one bit.

Interpolation
^^^^^^^^^^^^^^^

The DAC cores are often operated at very high sample rates in order to provide flexibility in output signal frequency. However, many applications use waveforms with bandwidths that are much smaller than the sample rate, so it would be very wasteful to store the waveform at the full sample rate when a smaller rate would suffice, especially because on-chip memory is a scarce resource. These goals reconciled by storing samples at a lower rate in memory and interpolating between them to feed the DAC core at its full rate. 

Interpolation can take many forms and is commonly used in data analysis, but one should note that many common types of interpolation (e.g., linear, cubic spline, etc.) will introduce additional spectral content outside the bandwidth of the original pulse and may require significant hardware resources to implement at high bandwidth. Fortunately, when a finite-bandwidth signal is sampled at a rate of at least twice its bandwidth, it can be perfectly reconstructed at any point in time with no loss of information or additional distortion (this is restatement of the Nyquist criterion). Furthermore, this optimal interpolation strategy is simple to implement in hardware; it consists of adding zeros in between the low-rate samples and low-pass filtering the resulting stream (for additional details about the mathematics of this operation, we recommend Ch. 10 of \cite{lyons}). Therefore, the only price paid for performing this interpolation is a small amount of additional latency for the samples to pass through the interpolation logic.

The RFSoC RF tile implements a reconfigurable interpolator just after the gearbox FIFO, so that the logic in the FPGA can provide data at a reduced rate but allow all further processing to occur at the full bandwidth of the DAC core. The interpolator block operates as described above; it inserts a given number of zero-valued samples between each input sample (such that its output sample rate matches that of the DAC core) and filters the result. The interpolator offers a selection of interpolation factors, but for a fixed input sample rate (given by the product of FPGA clock rate and the number of samples provided per clock cycle), the allowed output sample rate is constrained by the maximum rate of the DAC.

In Acadia the logic clock and the tile interface width are taken to be fixed, but may be adjusted with custom firmware. The interpolation factor and the DAC core sample rate may be adjusted dynamically, allowing flexibility in placing Nyquist zone boundaries. The default logic clock rate is 200 MHz and four complex samples are provided each clock cycle, resulting in a tile input rate of 800 MS/s. The DAC core has a maximum sample rate of 9.8 GS/s, so the interpolation factors and resulting DAC sample rates that may be used are: 1 (800 MS/s), 2 (1.6 GS/s), 3 (2.4 GS/s), 4 (3.2 GS/s), 5 (4.0 GS/s), 6 (4.8 GS/s), 8 (6.4 GS/s), 10 (8.0 GS/s), 12 (9.6 GS/s). Note that using the NCOs at sample rates above 7 GS/s requires special consideration; see below. 

Numerically-Controlled Oscillator (NCO)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Multi-band Crossbar
^^^^^^^^^^^^^^^^^^^^^

DAC Core
^^^^^^^^^^

Analog-to-Digital Converters (ADC)
------------------------------------

ADC Core
^^^^^^^^^^

Multi-band Crossbar
^^^^^^^^^^^^^^^^^^^^^

Numerically-Controlled Oscillator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Decimation
^^^^^^^^^^^^

Clock Distribution
--------------------

External Clock Inputs
^^^^^^^^^^^^^^^^^^^^^^^

The CLK104 Clock Synthesizer
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Synchronization Signals
^^^^^^^^^^^^^^^^^^^^^^^^^

Processing Subsystem (PS)
===========================

ARM Compute Cluster and Interconnects
---------------------------------------

General-Purpose Input/Output (GPIO) Signals
---------------------------------------------

Placeholder