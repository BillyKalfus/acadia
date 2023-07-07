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

 Digital-to-Analog Converters (DAC)
------------------------------------

 Interpolation
^^^^^^^^^^^^^^^

 Numerically-Controlled Oscillator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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

The sequencer may be thought of as a high-performance real-time CPU in that it accesses a memory containing "instructions" that govern how data flows through the internal datapath of the sequencer (the classification of whether something is or is not a CPU is largely academic pedantry rather than a description of actual capabilities, so comparing the sequencer to a CPU is primarily useful for building intuition about its behavior). Also like a CPU, the datapath of the sequencer is a controllable interconnect responsible for moving data from one place to another as directed by the instructions; however unlike a (typical) CPU, the data does not pass through any other logic on its way to its destination. Instead, the endpoints of the datapath (referred to as the sources and destinations) determine how data can be transformed or transported by the sequencer. For example, rather than having a native instruction to add numbers by routing data through an arithmetic logic unit (ALU) as it passes from source to destination (as is typically done in conventional CPUs), one would execute instructions that move the addends from their respective sources into the ALU, then retrieve the result when the addition is complete. This architecture offers quite a bit of flexiblity in the operations available to the sequencer while allowing the clock speed to remain high, since the "distance" between sources and destinations are not lengthened by the presence of processing logic (such as an ALU). In contrast to a multi-cycle datapath (in which registers are inserted into long datapath branches and instructions take multiple cycles to complete), the real-time nature of the sequencer's execution is maintained: every data transfer from a source to a destination takes one cycle. This behavior is extremely useful for distributed systems requiring a high degree of synchronicity, since this means that the sequencer is able to operate at the finest timebase resolution of the system. 

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

 Stack
^^^^^^^

 Bus
^^^^^

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

 ADC Sample FIFOs
^^^^^^^^^^^^^^^^^^

 Complex Multiplier with Accumulator (CMACC)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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

