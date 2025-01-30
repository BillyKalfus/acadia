 Introduction
===============

Modern experiments in quantum computing demand real-time sequencing and control flow on nanosecond timescales. The desire to apply various quantum gates conditioned on the results of device measurements imposes the requirement for more advanced capabilities than those offered by commercial arbitrary waveform generators (AWGs), and low tolerance for nondeterministic latencies or jitter while interacting with qubits requires that any processing logic be fully synchronous with waveform synthesis.

The high degree of programmability sought from a quantum control system makes interaction with high-level languages and hardware desirable, but the latency imparted by typical communication protocols and the instruction decoding needed to implement the extensive instruction sets supported by modern CPUs completely prohibit their integration into quantum control systems. This latency can become noticeable during the thousands of shots typically required of quantum measurements and is often too long for performing computation between shots (such as loading new parameter sets for sweeps or a new set of random gates into the FPGA in randomized benchmarking), let along during shots (such as filtering readout signals for real-time feedback). 

Because of this, custom control hardware for quantum computers satisfying the aforementioned requirements has been developed independently by multiple research groups [citation needed]. 
Most existing solutions implement a simple real-time processor in FPGA gateware which is capable of performing parameter sweeps, control flow, and oftentimes specialized computations (such as random number generation or matrix multiplication) onboard. Analog-to-digital converters (ADCs) and digital-to-analog converters (DACs) are connected to the FPGA, which can then orchstrate the synthesis, capture, and processing of microwave signals interacting with the quantum hardware in real time. Often, the instrument will be configured and managed by a conventional lab PC and will typically execute many ``shots'' of an experiment. As theoretical advances in quantum error correction became evermore prevalent and experimentalists began asking more of their control hardware, users sought to add capabilities to their instruments like advanced automated calibration routines or real-time error syndrome decoding. However, extending the performance of FPGA-based systems requires knowledge of digital design and computer architecture, which are not often components of physics curricula.

These challenges are not unlike those currently being encounted in wireless communications, in which the desire for higher bandwidth increases the demands both on the RF hardware and on the signal processing requirements of cellular base stations. In response, semiconductor manufacturers aimed to capitalize on these trends through the development of mixed-signal systems-on-chip (SoCs). We'll focus on the Xilinx RFSoC series of products, which offer large regions of FPGA fabric and arrays of ADCs and DACs on-chip, alongside a quad-core ARM processor (referred to as the Processing Subsystem (PS)) tightly integrated with the programmable logic (PL).

Targeted at directly synthesizing signals for wireless communications, the analog data converters in the RFSoC are able to directly synthesize signals up to approximately 10 GHz, offering a promising opportunity to alleviate the restrictions imposed by conventional pulse synthesis techniques when scaling quantum processors. The harmonics and image tones introduced by mixing elements exacerbate the issue of qubit frequency crowding, while driving with high power distorts pulses and introduces spurious emissions, thereby increasing the difficulty of driving parametric processes which require signals with extremely stable phase and frequency relationship. This often requires signals to be mixed with one another to achieve sufficient syntonization, but because of the high power required for driving a mixer along with its conversion loss and spectral broadening, a significant amount of noise is added in this process and the high degree of connectivity required quickly makes this technique impractical for more than a handful of channels.

In contrast, the DACs and ADCs in the RFSoC have high enough analog bandwidths and sample rates so that pulses intended to drive transitions in superconducting circuits may be directly synthesized without the need for nonlinear upconversion processes driven by local oscillators. Additional signal processing capabilities in the datapaths of the mixed-signal tiles implement features that are desirable for quantum control (described below), alleviating requirements of the FPGA fabric.

Furthermore, the low (but nondeterministic) latency of the interconnect between the PS and the PL allows one to offload computational tasks normally required of the control FPGA to the ARM processor, such as generating new waveforms in response to parameter sweeps. The FPGA fabric then only requires a simple sequencer capable of real-time execution and conditional control flow, and programs running on the PS will have direct access to wave synthesis/capture memory and sequencer instruction memory. 

These benefits (among others) motivate the implementation of a control system on the RFSoC, which we describe herein.

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

To take advantage of direct digital synthesis at microwave frequencies, sample rates of the synthesizing DAC core must be comparable to the desired carrier frequency. However, many applications do not require the signal envelopes which modulate the carrier to have bandwidths of this magnitude; they can be much smaller. Therefore, it would be very wasteful to store the pulse envelope in memory at the sample rate of the DAC core when a much smaller sample rate is sufficient for losslessly storing the envelope, but the DAC core still needs to be provided with data at its full sample rate. 

These requirements are reconciled by interpolating the low-bandwidth sample data stored in memory before passing it to the DAC core. Interpolation can take many forms and is commonly used in data analysis, but one should note that many common types of interpolation (e.g., linear, cubic spline, etc.) will introduce additional spectral content outside the bandwidth of the original pulse and may require significant logic resources to implement at high bandwidth. Fortunately, there is an optimal (and resource-efficient) way to interpolate between samples of band-limited data, as described in the Background section. 

The RFSoC Data Converter implements interpolation at the interface to the tile, so that the logic in the FPGA can provide data at a reduced rate but allow all further processing and synthesis occur at the full bandwidth of the DAC core. The interpolator block operates by inserting zero-valued samples between its inputs, such that its output sample rate matches that of the DAC core. Before exiting the block, the signal is filtered by a reconfigurable chain of digital FIR filters. Because the total filter transfer function is reconfigurable and because the interpolator can insert a controllable number of samples, the interpolator can function effectively for multiple interpolation factors. The available total interpolation factors in the RFSoC are 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, and 40. Note that there is an additional factor-of-two interpolation if the datapath is configured in IMR mode, as described in the section about numerically-controlled oscillators.

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

 Logic Design
==============

 Sequencer
-----------

The sequencer is a small real-time CPU that is responsible for coordinating actions across the system. It steps through a sequence of instructions, each of which moves data from one location in the internal datapath of the sequencer (the "sources") to another (the "destinations"). There is only one type of instruction, but many destination ports of the sequencer will take additional action when written to or provide access to logic units that carry out more complex operations. For example, rather than having a native instruction to add numbers by routing data through an arithmetic logic unit (ALU) as it passes from source to destination, one would execute instructions that move the addends from their respective sources into the ALU via its destination ports, then retrieve the result from its source port when the addition is complete. This architecture greatly reduces the critical path of the sequencer, allowing the clock speed to remain reasonably high while allowing the sequencer to fetch and execute . This behavior is extremely useful for distributed systems requiring a high degree of synchronicity, since this means that the sequencer is able to operate at the finest timebase resolution of the system. 

When the sequencer starts, it begins reading from instruction memory and executing instructions in sequence. The sequencer has only two native instructions: store parallel (STP) and store conditional (STC). During an STP instruction, the sequencer is able to take any two data sources and load them into any two destinations independently of one another. The sources and destinations connected to the datapath determine the capabilities of the sequencer, which we'll detail individually in the following sections. During an STC instruction, one data source may be conditionally written to a destination, depending on whether a user-specified condition is satisfied. Therefore, for destinations that execute actions when written to, this mechanism can intrinsically allow those actions to be executed conditionally.

As described earlier, the sources and destinations fully determine the capabilities of the system. We'll now describe the various sources and destinations in more detail.



 General-Purpose Registers
^^^^^^^^^^^^^^^^^^^^^^^^^^^

In an architecture centered around moving data from one place to another at high speed, it's incredibly useful to have extremely low-latency storage into which one can quickly stash data for reuse. In modern CPUs this is typically accomplished with a handful of registers implemented as flip-flops embedded in the CPU's datapath. The Acadia sequencer implements a similar approach, including eight 32-bit general-purpose registers. The set of registers may be thought of as a 32-bit eight-deep zero-latency memory with two read ports and two write ports with independent addresses. Correspondingly, in a single cycle two different registers can be updated with the values of two other registers.

 Digital Signal Processing (DSP) Slices
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

 Program Counter (PC)
^^^^^^^^^^^^^^^^^^^^^^

 Conditionality Engine
^^^^^^^^^^^^^^^^^^^^^^^

\begin{longtable} {@{}||c|>{\raggedright}p{2.5cm}|p{10cm}||@{}}
  \hline
  OP & Operation & Description \\ 
  \hline\hline
  \endfirsthead
  
  \hline
  OP & Operation & Description \\ 
  \hline\hline
  \endhead
  
  \hline
  \endfoot
  
  \hline
  \endlastfoot
  
  0 & or(SRC AND mask) & A bitwise AND is computed between the source value and the mask, and the result is reduced with a bitwise OR. This will evaluate to 1 when any bits that are set in the mask are also set in SRC, ignoring any additional bits in SRC which may be set. \\ \hline
  1 & or(SRC XOR mask) & This will evaluate to 1 when SRC does not equal MASK. \\ \hline
  2 & or((not SRC) AND mask) &  \\ \hline
  3 & or(SRC) & A reduced bitwise OR across all bits in SRC. This will evaluate to 1 when any bits in the source value are set.\\ \hline
  4 & not or(SRC AND mask) & \\ \hline
  5 & not or(SRC XOR mask) & A bitwise XOR is computed between the source value and the mask, the result is reduced with a bitwise OR, and the result is inverted. This will evaluate to 1 when SRC exactly matches the mask. \\ \hline
  6 & not or((not SRC) AND mask) & The source value is inverted, a bitwise AND is computed between the inverted source value and the mask, the result is reduced with a bitwise OR, and this value is inverted. This will evaluate to 1 when all bits that are set in the mask are also set in SRC, ignoring any additional bits in SRC which may be set.  \\ \hline
  7 & not or(SRC) & A reduced bitwise OR across all bits in SRC. \\ \hline
  8-31 & Reserved & These values are reserved and behavior is undefined. \\ \hline
\end{longtable}

 Stack
^^^^^^^

 Bus
^^^^^

 Sources
^^^^^^^^^

\begin{longtable} {@{}||c|>{\raggedright}p{2.5cm}|p{10cm}||@{}}
  \hline
  SRC & Source & Description\\ 
  \hline\hline
  \endfirsthead
  
  \hline
  SRC & Source & Description \\ 
  \hline\hline
  \endhead
  
  \hline
  \endfoot
  
  \hline
  \endlastfoot
  
  0-7 & R0-7 & The value of a particular general-purpose register. \\ \hline
  8 & Program Counter &  \\ \hline
  16 & IMM & The value of the IMM bitfield in the current instruction. \\ \hline
  24 & Test Value Register & \\ \hline
  32 & HEDGEHOG Flags & Input latching flags from the HEDGEHOG logic.\\ \hline
  40 & Stack Pop & \\ \hline
  48 & Bus Data Read & Reads the output of the bus and drives the read enable signal. \\ \hline
  56 & DSP Pattern Detect & The lower 16 bits are connected to the DSP slice PATTERNDETECT signals. The upper 16 bits are connected to the PATTERNDETECTPAST signals. \\ \hline
  64-71 & DSP P & The lower 32 bits of the DSP slice P registers. \\ \hline
  
\end{longtable}

 Destinations
^^^^^^^^^^^^^^

\begin{longtable}{@{}||c|>{\raggedright}p{2.5cm}|p{10cm}||@{}}
  \hline
  DEST & Destination & Description \\ 
  \hline\hline
  \endfirsthead
  
  \hline
  DEST & Destination & Description \\ 
  \hline\hline
  \endhead
  
  \hline
  \endfoot
  
  \hline
  \endlastfoot

  0-7 & R0-7 & General purpose registers R0-R7. \\ \hline
  8 & Program Counter & \\ \hline
  16 & Instruction Hold & Writing to this location will cause the instruction memory output to hold its current value. When the instruction is complete, the Program Counter will be loaded with the value written to this destination. \\ \hline
  24 & Branch Mask Register & The register containing the mask value used in branching instructions. \\ \hline
  40 & Stack Push & \\ \hline
  48 & Bus Address Register & The register which indexes the bus.\\ \hline
  56 & Bus Data Write & \\ \hline
  64-71 & DSP0-7 Configuration & Configures a DSP slice by writing to the OPMODE, ALUMODE, and CIN registers, as well as a register controlling CEP. Bits 3-0 are connected to the ALUMODE input. Bits 12-4 are connected to the OPMODE input. Bit 13 is connected to CIN. Bit 14 is connected to RSTP. Bits 16-15 control a register whose output is connected to the CEP input; if 0, it is unchanged. If 1, it is set until manually cleared. If 2, the register is cleared.  If 3, it is pulsed for one cycle. \\ \hline
  72-79 & DSP AB & Loads DSP0-7 AB inputs with data. \\ \hline
  80-87 & DSP C & Loads DSP0-7 C inputs with data. \\ \hline

\end{longtable}

 Instructions
^^^^^^^^^^^^^^

STP \newline \newline Store Data Parallel & 
    \begin{tabular}{@{}c|p{3.2cm}|p{6.8cm}@{}}
      127-113: & Reserved & \\ \hline
      112: & 0 & \\ \hline
      111-105: & Reserved & \\ \hline
      104: & PUSH\_RETURN & When this bit is set, the value of the Program Counter minus 1 (to account for memory latency) is pushed to the stack if the PC is written. Note that if a particular destination is specifying the stack, then that transfer will override this bit. \\ \hline
      103-96: & SRC1 & \\ \hline
      95-88: & SRC2 & \\ \hline
      87-80: & DEST1 & \\ \hline
      79-72: & DEST2 & \\ \hline
      71-69: & Reserved & \\ \hline
      68: & DSP\_CEP\_EN & \\ \hline
      67: & Reserved & \\ \hline
      66-64: & DSP\_CEP & \\ \hline
      63-32: & IMM1 & \\ \hline
      31-0: & IMM2 & \\ \hline
    \end{tabular} \\ \hline
  
  STC \newline \newline Store Data Conditional & 
    \begin{tabular}{@{}c|p{3.2cm}|p{6.8cm}@{}}
      127-113: & Reserved & \\ \hline
      112: & 1 & \\ \hline
      111-105: & Reserved & \\ \hline
      105: & PUSH\_RETURN & Identical to PUSH\_RETURN in the STP instruction. \\ \hline
      103-96: & SRC\_STVAL & The source to store data from, should the condition be satisfied.\\ \hline
      95-88: & SRC\_TVAL & The source providing data to test a particular logical condition.\\ \hline
      87-80: & DEST\_STVAL & The destination at which the data from SRC\_STVAL will be stored if the condition is satisfied.\\ \hline
      79-77: & Reserved & \\ \hline
      76-72: & OP & The operation executed between the test value and the mask register to determine whether a jump will occur. See Section \ref{sec_condition_table} for a description of values of this field. \\ \hline
      71-69: & Reserved & \\ \hline
      68: & DSP\_CEP\_EN & \\ \hline
      67: & Reserved & \\ \hline
      66-64: & DSP\_CEP & \\ \hline
      63-32: & IMM\_STVAL & \\ \hline
      31-0: & IMM\_TVAL & \\ \hline
    \end{tabular} \\ \hline
\end{longtable}

 Memory and Communication Infrastructure
-----------------------------------------

 Cache Memory
^^^^^^^^^^^^^^

 Sequencer Instruction Memory
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

 Sequencer AXI Crossbar
^^^^^^^^^^^^^^^^^^^^^^^^

 Configuration AXI Interconnect
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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

 Processing Subsystem (PS)
---------------------------

 ARM Compute Cluster and Interconnects
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

 General-Purpose Input/Output (GPIO) Signals
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

 Integrated AXI DMA
^^^^^^^^^^^^^^^^^^^^
