import os
import mmap
import logging
import struct
import builtins
import re
import json
from dataclasses import dataclass
from functools import wraps, reduce
from typing import Union, Callable, Literal, Any, List, Dict
from binascii import hexlify,unhexlify
from operator import or_

import numpy as np

from .waveforms import WaveformMemory
from .compiler import ManagedResource, ManagedMemory, Processor, Synchronizer, Operation, Symbol
from .sequencer import Sequencer, Source, is_numeric
from .peripherals import RFClk, PSGPIO, ZDMA, AXISSwitch
from .firmware import Firmware
from .firmware_configurations import CONFIG_200

import acadia.utils as utils
import acadia.rfdc as rfdc
from acadia.rfdc import Channel

__all__ = ["DMASynchronizer", 
           "RFDCSynchronizer", 
           "StreamConfiguration"
           "Acadia"]

logger = logging.getLogger("acadia")

class DMASynchronizer(Synchronizer):
    """
    Synchronizes DMA triggers.
    """
    
    ARBITRARY_CONTINUED = 0
    ARBITRARY = 1
    CONSTANT_CONTINUED = 2
    DWELL = 3
    BARRIER = 4
    DIRECT = 5
    
    def __call__(self, *args, **kwargs):
        if not isinstance(Processor.active_processor(), Sequencer):
            raise TypeError("Synchronization is only supported for contexts of"
                            " a `Sequencer` object. Either enter an appropriate"
                            " context to enforce synchronization or call the"
                            " appropriate method to act directly on the"
                            " hardware.")
            
        self._dma_trigger = kwargs.pop("trigger", True)
        self._dma_block = kwargs.pop("block", self._dma_trigger) # don't block if we don't trigger
        return super().__call__(*args, **kwargs)

    @staticmethod
    def create_schedules(calls) -> List[Dict[Channel,List[Dict[str,Any]]]]:
        """
        Converts a sequence of function calls into individual
        subschedules separated by barriers. The complete schedule is a list, and
        each element of this list is a dict representing a single subschedule.
        The dict's keys are channels, and the values are lists containing
        all the commands issued on the channel during the subschedule.
        These commands are themselves dicts containing necessary arguments
        for commanding the DMA.
        """
        schedules = [{}]

        # A direct write to the DMA command FIFO prevents us from scheduling anything after it,
        # so let's keep track of whether we found one
        has_direct = False 

        for idx_call,call in enumerate(calls):
            function,acadia,args,kwargs,retval = call.values()

            # For DMA command calls, aggregate the details of the call and organize them by channel
            if function in [DMASynchronizer.ARBITRARY, DMASynchronizer.ARBITRARY_CONTINUED, DMASynchronizer.CONSTANT_CONTINUED, DMASynchronizer.DWELL]:
                
                if "length" not in kwargs:
                    raise KeyError(f"Unable to locate length in kwargs {kwargs}")

                # Extract and validate the channel
                if "channel" not in kwargs:
                    raise KeyError(f"Unable to locate channel in kwargs {kwargs}")
                
                channel = kwargs["channel"]

                if not isinstance(channel, Channel):
                    raise TypeError(f"Channel must be of type `Channel` (received"
                                    f" {channel}).")

                # Note that the values of the function constants are chosen
                # to match the command values for command_dma, so we can pass it 
                # right into the eventual function call arguments
                command_dict = {
                    "length": kwargs["length"],
                    "command_type": function,
                    "length_is_minus_one": kwargs.get("length_is_minus_one", False)
                }
                if function == DMASynchronizer.ARBITRARY:
                    if "address" not in kwargs:
                        raise KeyError(f"Unable to locate address in kwargs for arbitrary DMA command: {kwargs}")

                    command_dict["address"] = kwargs["address"]
                    
                schedule_dict = schedules[-1]
                if channel in schedule_dict:
                    schedule_dict[channel].append(command_dict)
                else:
                    schedule_dict[channel] = [command_dict]
                
            elif function == DMASynchronizer.BARRIER:
                # We can't put a barrier after a direct command
                if has_direct:
                    raise ValueError(f"Can't place barrier after a DMA direct command")

                # Start a new subschedule, new commands are automatically
                # added to the last one in the list
                schedules.append({})

            elif function == DMASynchronizer.DIRECT:
                if "channel" not in kwargs:
                    raise KeyError(f"Unable to locate channel in kwargs {kwargs}")

                has_direct = True
                command_dict = {
                    "command_type": function,
                    "command": kwargs["command"]
                }

                schedule_dict = schedules[-1]
                if kwargs["channel"] in schedule_dict:
                    schedule_dict[kwargs["channel"]].append(command_dict)
                else:
                    schedule_dict[kwargs["channel"]] = [command_dict]

            else:
                raise ValueError(f"Synchronizer called with unrecognized"
                                 f" function code: {function}")

        return schedules

    @staticmethod
    def calculate_subschedule_dwells(schedule, indeterminate_types: List, last: bool = False) -> tuple[Dict[Channel,List[Dict[str,Any]]], Operation, Dict]:
        """
        Given a list of subschedules within a single synchronizer, the 
        barriers are reconciled by inserting dwells on channels prior to each 
        barrier so that all channels are aligned in their command execution 
        at the point of the barrier. The total length of the subschedule is 
        calculated by first finding the longest total sequence on any channel in the 
        subschedule, and defining its endpoint to be the total length of the 
        subschedule. Then, dwells are inserted on any other channels 
        that are used after the barrier, so that the total length of all their 
        commands in the current subschedule matches the longest one. This means that 
        at the point when the longest sequence completes, the sequences for all other 
        channels are completing as well, thus guaranteeing that all channels begin the 
        following subschedule at the same time (the time of the barrier).

        For example, let's assume that in a given subschedule, channel n has a sequence 
        of commands with total length l_n and another channel m has a sequence of total 
        length l_m. If l_m > l_n, then a dwell will be inserted on channel n of length 
        l_m - l_n so that both channels are completing their subschedules at a time 
        l_m after they started. If this subschedule is followed by another one with commands
        on a third channel p, then a dwell will be inserted in the current subschedule
        on channel p of length l_m, so that it also begins its subschedule at the same time
        as channels m and n.

        Because some commands may be of indeterminate length, determining the length
        of a subschedule (and therefore, deciding dwells to precede future commands) 
        is not always possible (or can lead to unacceptable overhead to compute 
        them at runtime). Therefore, when a command in a subschedule has an indeterminate 
        length, the following strategy is used:

        - All other channels that require a dwell compensating for the length of the 
        indeterminate command will receive a dwell of *matching* length. 
        
        - The channel with the most indeterminate commands is assumed to be the 
        longest sequence, regardless of the lengths of any other channel, 
        determinate or not.

        - Dwells are calculated for determinate and indeterminate commands separately. 
        
        The following examples demonstrate this strategy:
        
        - Suppose that channel m has a determinate command of length 5 and an 
        indeterminate command of length l_m, and a channel n has a determinate 
        command of length 3 and an indeterminate command of length l_n. If it 
        cannot be known at compile time whether l_m = l_n, an error is raised. 
        The actual value need not be known, they just must be known to be equal. 
        If they are equal, then channel n will receive a dwell of length 5-3 = 2 
        to compensate for the difference in determinate command lengths. The total
        length of both subschedules is then l_m + 5.

        - Suppose that channel m has a determinate command of length 5 and an 
        indeterminate command of length l_m, and a channel n has a determinate 
        command of length 3 and two indeterminate commands of length l_n1 and l_n2.
        If it cannot be known at compile time whether l_m is equal to l_n1 or l_n2, 
        an error is raised. Suppose without loss of generality that l_m = l_n1. 
        Then, channel m will receive a dwell of length l_n2 so that the total
        length of indeterminate commands on both channels is l_n1 + l_n2. Channel n 
        will also receive a dwell of length 5-3 = 2 to compensate for the 
        difference in determinate commands. The total length of both subschedules 
        is then l_n1 + l_n2 + 5.

        Equality between indeterminate command lengths can only be established 
        when the two lengths are Source objects referring to the same Register 
        or DSP (but they need not be the same object). Otherwise, they are 
        assumed to be unequal.

        Only Registers and DSPs are valid for use as indeterminate command sources.
        Any other source will throw an error.

        Lengths given by Symbols and Operations are assumed to be determinate, 
        since the values of Symbols and Operations are required to be 
        resolveable by assembly time. Length calculations are kept symbolic throughout
        compilation, so Symbols and Operations that are unassigned or unresolveable 
        at compile time are still assumed to be determinate and will be computed at 
        assembly time.
        """

        # Let's first validate the subschedules and make sure that 
        # everything is valid and that they contain all the necessary information
        
        if not isinstance(schedule, dict):
            raise TypeError(f"Received schedule of invalid type: {type(schedule)}")

        logger.debug(f"Schedule contains {len(schedule)} channels")

        # Keep track of all the indeterminate commands scheduled on each channel, so that
        # we can make sure that they're all resolveable
        # While we're iterating, we'll also gather the lengths of all the determinate commands
        # so that we can compute dwells for these later
        indeterminate_commands = {c: [] for c in schedule.keys()}
        determinate_lengths = {c: 0 for c in schedule.keys()}
        for channel,channel_schedule in schedule.items():
            if not isinstance(channel, Channel):
                raise TypeError(f"Received channel of invalid type: {type(channel)}")

            if not isinstance(channel_schedule, list):
                raise TypeError(f"Received channel schedule of invalid type: {type(channel_schedule)}")

            logger.debug(f"Processing commands in subschedule for channel"
                         f" {str(channel)} ({len(channel_schedule)} commands)")

            for command in channel_schedule:
                if not isinstance(command, dict):
                    raise TypeError(f"Found command of invalid type: {type(command)}")  

                # We know that if we receive a direct command, there can't be a barrier after it
                # this means that we must be in the last subschedule. However, we shouldn't call
                # calculate_subschedule_dwells for the last subschedule
                if command["command_type"] == DMASynchronizer.DIRECT:
                    raise ValueError(f"Found a DIRECT command in a subschedule passed to"
                                     f" calculate_subschedule_dwells: {command}")
                
                if "length" not in command:
                    raise KeyError(f"Command missing length")

                if "command_type" not in command:
                    raise KeyError(f"Command missing command type")

                if command["command_type"] == DMASynchronizer.ARBITRARY and "address" not in command:
                    raise KeyError(f"Arbitrary command missing address")

                length = command["length"]
                if isinstance(length, tuple(indeterminate_types)):
                    # Either a register or a DSP
                    logger.debug(f"Found indeterminate command from source {str(length)}")
                    indeterminate_commands[channel].append(command)
                    
                elif np.issubdtype(type(length), int) or isinstance(length, (np.uint32, np.int32)) or isinstance(length, (Symbol, Operation)):
                    if command["length_is_minus_one"]:
                        determinate_lengths[channel] += length + 1
                    else:
                        determinate_lengths[channel] += length
                else:
                    raise TypeError(f"Received command length of invalid type: {type(length)}")

        logger.debug(f"Command types validated."
                    f" Indeterminate-length command counts:"
                    f" {', '.join([f'{c}: {len(l)}' for c,l in indeterminate_commands.items()])}")

        # All the types have been validated. If this isn't the last schedule in the synchronizer,
        # we need to make sure that the conditions are met for us to insert the appropriate dwells
        # for the next one
        if last:
            logger.debug(f"No dwells needed for last subschedule in synchronizer")
            return {}

        # In preparation for the upcoming barrier, we need to make sure that we can insert 
        # dwells of appropriate length on all the channels with indeterminate commands
        # We'll sort the grouping of channels with indeterminate commands by the number of indeterminate
        # commands they have (in reverse order, so that the channel with the most indeterminate commands is first)
        indeterminate_commands_channels_sorted = sorted(indeterminate_commands.keys(), key=lambda l: len(indeterminate_commands[l]), reverse=True)
        
        # We need to make sure that the sets of indeterminate commands on every other channel 
        # are each a subset of those on the channel with the most
        longest_indeterminate_sequence = indeterminate_commands[indeterminate_commands_channels_sorted[0]]
        logger.debug(f"Longest indeterminate sequence (on channel {indeterminate_commands_channels_sorted[0]}) has {len(longest_indeterminate_sequence)} command(s)")

        for channel in indeterminate_commands_channels_sorted:
            for command in indeterminate_commands[channel]:
                if command not in longest_indeterminate_sequence:
                    raise ValueError(f"Command on channel {channel}"
                                    f" not found in longest sequence.")

        logger.debug(f"Indeterminate subsets validated.")

        # Use the lists generated above to determine the dwells we should add to each 
        # channel to compensate for the other channels' indeterminate commands
        logger.debug(f"Reconciling indeterminate dwells")
        dwell_commands = {c: [] for c in schedule.keys()}
        for channel,channel_schedule in schedule.items():
            for command in longest_indeterminate_sequence:
                if command not in channel_schedule:
                    cmd = {k:v for k,v in command.items() if k != "command_type"}
                    cmd["command_type"] = DMASynchronizer.DWELL
                    dwell_commands[channel].append(cmd)
        logger.debug("Reconciled.")

        # Add the determinate dwells
        # We need dedicated logic to check if the lengths list has only one element because if we pass only one
        # argument to max(), it will try to iterate over it, and if we pass the argument to max() as a list with
        # only one element, the compiler won't detect the list argument as numeric and will fail to compile it
        # Fortunately, this is also a good opportunity to avoid creating NOPs, because when there's only one command
        # of determinate length, we can avoid inserting a nulled command on the channel that it pushes to
        if len(determinate_lengths) == 1:
            longest_determinate_sequence_length = list(determinate_lengths.values())[0]
            longest_determinate_sequence_channel = list(determinate_lengths.keys())[0]
            logger.debug(f"Only one determinate-length command found in subschedule"
                        f" (on channel {str(longest_determinate_sequence_channel)},"
                        f" length {longest_determinate_sequence_length}),"
                        f" creating dwell of identical length for other channels in subschedule")
            for channel in schedule.keys():
                if channel != longest_determinate_sequence_channel:
                    dwell_commands[channel].append({
                        "command_type": DMASynchronizer.DWELL,
                        "length": longest_determinate_sequence_length,
                        "length_is_minus_one": False
                    })
        else:
            longest_determinate_sequence_length = Operation(builtins.max, *list(determinate_lengths.values()))
            logger.debug(f"Determinate dwells validated."
                        f" Channels with determinate-length commands:"
                        f" {', '.join([f'{c}: {l}' for c,l in determinate_lengths.items()])}")
            
            for channel,channel_schedule in schedule.items():
                dwell_commands[channel].append({
                    "command_type": DMASynchronizer.DWELL,
                    "length": longest_determinate_sequence_length - determinate_lengths[channel],
                    "length_is_minus_one": False
                })

        return dwell_commands, longest_determinate_sequence_length, longest_indeterminate_sequence


    @staticmethod
    def merge_schedules(schedules: List, indeterminate_types: List) -> Dict[Channel,List[Dict[str,Any]]]:
        """
        Combine schedules, adding padding as necessary to align channel 
        schedules are barrier boundaries. Note that the elements of 
        the provided argument will be modified, extending the individual
        schedules with dwells as necessary.

        The return value is a single combined schedule for all channels
        involved in any provided schedules.
        """
        # Determine the dwells associated with each sub-schedule 
        # except for the last one, since no dwell is needed for that.
        # We can also safely call calculate_subschedule_dwells on every 
        # subschedule we iterate over, since direct commands can only be in the last one
        logger.debug(f"Merging {len(schedules)} subschedules")
        for idx_schedule in range(len(schedules)-1):
            logger.debug(f"Calculating dwells for subschedule {idx_schedule}")
            dwell_commands, longest_determinate_sequence_length, longest_indeterminate_sequence = DMASynchronizer.calculate_subschedule_dwells(schedules[idx_schedule], indeterminate_types)
            
            # Add dwells to channels that need them
            logger.debug(f"Subschedule {idx_schedule} has {len(dwell_commands)} channels with added alignment dwells")
            for channel,channel_dwells in dwell_commands.items():
                logger.debug(f"{str(channel)}: {len(channel_dwells)} dwells")
                schedules[idx_schedule][channel].extend(channel_dwells)

            # Take the list of dwells created for this subschedule and
            # add dwells for channels used in future subschedules that 
            # didn't have anything scheduled here
            logger.debug(f"Adding dwells to channels in future subschedules")
            for idx_next_schedule in range(idx_schedule+1, len(schedules)):
                logger.debug(f"Examining future subschedule {idx_next_schedule}")
                for channel in schedules[idx_next_schedule].keys():
                    if channel in schedules[idx_schedule]:
                        logging.debug(f"Channel {str(channel)} already in current schedule, no compensating dwells added")
                    else:
                        # We found a channel in a future subschedule that doesn't have 
                        # anything in the current subschedule, so we need to add enough dwells
                        # to compensate for this full subschedule
                        logging.debug(f"Channel {str(channel)} found in future subschedule {idx_next_schedule}"
                                      f" with no commands in the current subschedule ({idx_schedule})")
                        new_schedule = []
                        for cmd in longest_indeterminate_sequence:
                            new_cmd = {k:v for k,v in cmd.items() if k != "command_type"}
                            new_cmd["command_type"] = DMASynchronizer.DWELL
                            new_schedule.append(new_cmd)

                        logging.debug(f"Added {len(new_schedule)} indeterminate dwells to {str(channel)}")
                        
                        # Finally, add the determinate part of the current subschedule
                        new_schedule.append({
                            "command_type": DMASynchronizer.DWELL,
                            "length": longest_determinate_sequence_length, 
                            "length_is_minus_one": False
                        })

                        # Since this channel has no entry in the master list, 
                        # we can just assign it here
                        schedules[idx_schedule][channel] = new_schedule
        
        # We've now properly aligned every subschedule and added dwells to them, so we can combine them all
        logger.debug(f"Combining all compensated subschedules")
        combined_schedules = {}
        for idx_schedule,schedule in enumerate(schedules):
            logger.debug(f"Adding commands for subschedule {idx_schedule}")
            for channel, channel_schedule in schedule.items():
                logger.debug(f"Adding {len(channel_schedule)} commands for channel {str(channel)}")
                if channel not in combined_schedules:
                    combined_schedules[channel] = []
                combined_schedules[channel].extend(channel_schedule)

        return combined_schedules

    @staticmethod
    def calculate_trigger_delay(
        combined_schedules,
        is_dma_bus_port_pipelined: List[bool],
        is_dma_trigger_dataport_bus_port_pipelined: bool,
        dma_trigger_dataport_output_pipeline_cycles: List[bool],
        dma_fifo_latencies: Dict[str,int]
    ) -> int:
        """
        There's a small latency before the descriptor appears at the DMA FIFO output after pushing to it.
        Because of this, we can't trigger immediately after pushing to the DMA FIFO. if there
        are enough other instructions between when we push the first command to all channels and when we 
        trigger, this could make up for it, but if there aren't, we need to delay manually 
        
        First note that the DMA receives the trigger synchronously, so when 
        trigger goes high, the DMA loads the FIFO output at the next cycle. This means
        that at the latest, the FIFO must update its output with the newly-pushed
        data at the same edge that trigger is raised high.
         
        We first need to know how long data takes to propagate through the FIFO.
        Let's define a latency of zero to mean that the FIFO is combinational; if we
        push to the FIFO, it immediately appears at the output, and in principle one 
        could raise trigger in the same cycle. A latency of 1 means that we could
        trigger in the next cycle immediately after pushing. Because of the architecture
        of the sequencer's bus, we can't trigger in the same cycle as we push to the FIFO, 
        so if the FIFO has a latency of 1, we don't need to insert any delays.
        
        Simulation tells us the FIFO latency, and this is stored in the firmware configuration.
        Now, the bus also doesn't necessarily have the same propagation delay from the sequencer to the DMA
        as it does to the trigger dataport. These values are stored in the firmware configuration, so we 
        can start by figuring out which channel in the complete schedule has the longest propagation to its
        DMA register interface, since this sets the limit on how long we need to wait 
        """
        push_propagations = {}
        for channel in combined_schedules.keys():
            push_propagations[channel] = 1 if is_dma_bus_port_pipelined[channel.num() + (0 if channel.is_dac else 16)] else 0

        # Then we can find the same quantities for the trigger
        trigger_propagations = {}
        for channel in combined_schedules.keys():
            trigger_propagations[channel] = dma_trigger_dataport_output_pipeline_cycles[channel.num() + (0 if channel.is_dac else 16)]
            if is_dma_trigger_dataport_bus_port_pipelined:
                trigger_propagations[channel] += 1

        # Now we can find the required number of cycles between when the first push happens and when the trigger is applied
        # based on when they actually reach the DMAs
        required_delays = {}
        for channel in combined_schedules.keys():
            # If the sequencer could trigger in the same cycle as pushing to the FIFO, how far apart would they arrive at the DMA?
            push_to_trigger_time = trigger_propagations[channel] - push_propagations[channel]
            
            # So, determine how many delay cycles that we would still need in order to ensure that the trigger arrives
            # a sufficient number of cycles after we push
            required_delays[channel] = dma_fifo_latencies[channel] - push_to_trigger_time
        
        # We only need as much latency as is necessary to appropriately separate 
        # the first FIFO push for a given channel and its corresponding trigger. 
        # However, if we write multiple times to a FIFO, this counts as cycles that
        # separate the first push from the trigger, so we don't need to add as many
        # NOPs
        # Therefore, we'll figure out how many pushes we have in the schedule after 
        # we've added the first push to each necessary channel.
        # DMA commands were added in an interleaved way, so all we need to do is figure out
        # how many commands are in the schedule across all channels after the first one from each
        num_pushes_after_last_first_push = sum([len(s)-1 for s in combined_schedules.values()])

        # Now we'll figure out how many cycles in total we need between the push and the trigger
        # TODO: if different DMAs have different amounts of required latency, we could
        # determine individually how much each channel needs. we'll ignore this for
        # now and just use the DMA that requires the longest delay, and verify that
        # we have at least that much. it will be typical that the propagation for both 
        # the DMA registers and the trigger dataport will be the same for all the DMAs 
        # anyway
        required_delay = max(required_delays.values())
        
        return max(0, required_delay - num_pushes_after_last_first_push)

    
    def __exit__(self, exc_type, exc_val, exc_tb):        
        self._acadia = None

        logger.debug(f"DMA synchronizer exited with {len(self._calls)} function calls, processing commands")

        if len(self._calls) == 0:
            raise ValueError("Empty synchronizer")
        
        # Extract an acadia object from one of the calls
        for idx_call,call in enumerate(self._calls):
            function,acadia,args,kwargs,retval = call.values()
            
            if self._acadia is None:
                self._acadia = acadia
            elif acadia is not self._acadia:
                raise ValueError(f"Unable to synchronize different instances"
                                 f" of `Acadia`")

        # Create individual subschedules from the total list of calls
        logger.debug("Creating subschedules")
        schedules = DMASynchronizer.create_schedules(self._calls)

        logger.debug(f"Created {len(schedules)} subschedules")
        for idx_schedule, schedule in enumerate(schedules):
            count_str = ', '.join([f'{str(c)} ({len(l)} commands)' for c,l in schedule.items()])
            logger.debug(f"Subschedule {idx_schedule}"
                f" involves the following channels: {count_str}")

        if len(schedules) == 1 and len(schedules[0]) == 0:
            raise ValueError(f"Empty synchronizer")

        # Insert dwells and combine the schedules 
        combined_schedules = DMASynchronizer.merge_schedules(schedules, indeterminate_types=[self._acadia.sequencer().Register, self._acadia.sequencer().DSP])

        # Now actually command the DMA to trigger
        # For latency reasons discussed below, we'll interleave the channels that
        # we push to, to maximize the time in between when a channel gets its first
        # push and the eventual trigger
        longest_schedule_length = max([len(s) for s in combined_schedules.values()])
        for i in range(longest_schedule_length):
            for channel, channel_schedule in combined_schedules.items():
                if i < len(channel_schedule):
                    command = channel_schedule[i]

                    # Convert direct commands to arbitrary, 
                    # since the direct commands is only needed for scheduling and validation
                    if command["command_type"] == DMASynchronizer.DIRECT:
                        command["command_type"] = DMASynchronizer.ARBITRARY
                        
                    self._acadia.command_dma(channel=channel, **command)

        dma_mask = reduce(or_, [(1 << (c.num() + (0 if c.is_dac else 16))) for c in combined_schedules.keys()])

        if self._dma_trigger:
            nops = DMASynchronizer.calculate_trigger_delay(
                combined_schedules,
                is_dma_bus_port_pipelined=self._acadia._firmware["sequencer_bus"]["dma_pipeline"],
                is_dma_trigger_dataport_bus_port_pipelined=self._acadia._firmware["sequencer_bus"]["dma_trigger_dataport"]["bus_pipeline"],
                dma_trigger_dataport_output_pipeline_cycles=self._acadia._firmware["sequencer_bus"]["dma_trigger_dataport"]["pipeline"],
                dma_fifo_latencies={c: self._acadia._firmware["rfdc"]["dac" if c.is_dac else "adc"]["dma_fifo_latency"][c.num()] for c in combined_schedules.keys()}
            )

            for _ in range(nops):
                self._acadia.sequencer().nop(comment=f"Delay accounting for DMA FIFO latency")
            
            # The only parent object that we could have had was an Acadia object,
            # so we know on which object we should call dma_trigger
            dma_trigger_device = self._acadia._firmware.sequencer_bus_decoder["dma_trigger"]
            self._acadia.sequencer().bus_write(address=dma_trigger_device.address().value(),
                            data=dma_mask,
                            comment="Trigger DMAs")

        if self._dma_block:
            # Wait until all the DMAs in the mask have completed
            dma_running_device = self._acadia._firmware.sequencer_bus_decoder["dma_running"]
            bus_op = self._acadia.sequencer().bus_read(dma_running_device.address().value(),
                        latency=self._acadia._bus_latency("dma_running"))
            with self._acadia.sequencer().repeat_until(bus_op & dma_mask == 0):
                pass

        super().__exit__(exc_type, exc_val, exc_tb)

class RFDCSynchronizer(Synchronizer):
    """
    Synchronizes DMA triggers, frequency and phase updates for NCOs, 
    DAC VOP and ADC DSA updates for the analog datapaths, and DAC TDD signals. 
    The constants below indicate how functions should be named in order to
    carry out the correct behavior in the synchronizer. For synchronized 
    functions that don't have the channel to be acted on as a parent, the 
    first positional argument must be the channel (if the channel is not 
    expected to be passed in as a keyword argument; if so, the corresponding
    keyword value will be used).
    """

    NCO_FREQUENCY = 2
    NCO_PHASE = 3
    NCO_PHASE_RESET = 4
    VOP = 5
    DSA = 6
    TDD = 7
    
    def __call__(self, *args, **kwargs):
        if not isinstance(Processor.active_processor(), Sequencer):
            raise TypeError("Synchronization is only supported for contexts of"
                            " a `Sequencer` object. Either enter an appropriate"
                            " context to enforce synchronization or call the"
                            " appropriate method to act directly on the"
                            " hardware.")

        self._nco_pl_event = kwargs.pop("nco_pl_event", False)
        return super().__call__(*args, **kwargs)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Get a reference to the Sequencer
        proc = Processor.active_processor()
        
        # Keep track of the aggregate values of all the calls
        nco_phase_reset = 0
        nco_update_enables = [0]*8
        nco_update_request = 0
        vop_dsa_update_reg = 0
            
        # The DAC VOP codes each have their own register but the DSA codes
        # are stored together by tile, so we need to aggregate
        tile_dsa_codes = [0]*4
        
        tdd_mode_set_reg = 0
        tdd_mode_clear_reg = 0
        
        self._acadia = None
        
        for call in self._calls:
            function,acadia,args,kwargs,retval = call.values()
            
            if self._acadia is None:
                self._acadia = acadia
            elif acadia is not self._acadia:
                raise ValueError(f"Unable to synchronize different instances of `Acadia`")

            channel = kwargs["channel"] if "channel" in kwargs else args[0]
            if not isinstance(channel, Channel):
                raise TypeError(f"Unable to identify channel (received {channel}).")
            
            
            rfdc_bit_position = 1 << (channel.num() if channel.is_dac else channel.num()+16)
                
            if function == RFDCSynchronizer.NCO_FREQUENCY:
                if isinstance(proc, Sequencer):
                    # The bit position for the channel in the update request and 
                    # phase reset registers
                    nco_update_request |= 1 << ((channel.tile+4) if not channel.is_dac else channel.tile)

                    # Which register for setting the update enable pins does this 
                    # channel belong to?
                    update_enable_reg = 4*channel.tile + (4 if not channel.is_dac else 0)

                    # if kwargs["low"]:
                    nco_update_enables[update_enable_reg] |= (1 << 0) << (6*channel.block)
                    # if kwargs["mid"]:
                    nco_update_enables[update_enable_reg] |= (1 << 1) << (6*channel.block)
                    # if kwargs["high"]:
                    nco_update_enables[update_enable_reg] |= (1 << 2) << (6*channel.block)

            elif function == RFDCSynchronizer.NCO_PHASE:
                if isinstance(proc, Sequencer):
                    # The bit position for the channel in the update request and 
                    # phase reset registers
                    nco_update_request |= 1 << ((channel.tile+4) if not channel.is_dac else channel.tile)

                    # Which register for setting the update enable pins does this 
                    # channel belong to?
                    update_enable_reg = 4*channel.tile + (4 if not channel.is_dac else 0)

                    # if kwargs["low"]:
                    nco_update_enables[update_enable_reg] |= (1 << 3) << (6*channel.block)
                    # if kwargs["high"]:
                    nco_update_enables[update_enable_reg] |= (1 << 4) << (6*channel.block)

            elif function == RFDCSynchronizer.NCO_PHASE_RESET:
                if isinstance(proc, Sequencer):
                    # The bit position for the channel in the update request and 
                    # phase reset registers
                    nco_update_request |= 1 << ((channel.tile+4) if not channel.is_dac else channel.tile)

                    # Which register for setting the update enable pins does this 
                    # channel belong to?
                    update_enable_reg = 4*channel.tile + (4 if not channel.is_dac else 0)

                    nco_phase_reset |= rfdc_bit_position
                    nco_update_enables[update_enable_reg] |= (1 << 5) << (6*channel.block)
                
            elif function == RFDCSynchronizer.VOP:
                if isinstance(proc, Sequencer):
                    vop_dsa_update_reg |= 1 << (4*channel.tile + channel.block)
                
            elif function == RFDCSynchronizer.DSA:
                if isinstance(proc, Sequencer):
                    vop_dsa_update_reg |= 1 << (16 + channel.tile)
                    data = args[0] << (channel.block*5)
                    mask = 0b11111 << (channel.block*5)
                    tile_dsa_codes[channel.tile] = (tile_dsa_codes[channel.tile] & ~mask) | data
                
            elif function == RFDCSynchronizer.TDD:
                if isinstance(proc, Sequencer):
                    if args[0]:
                        tdd_mode_set_reg |= rfdc_bit_position
                    else:
                        tdd_mode_clear_reg |= rfdc_bit_position
                else:
                    raise TypeError("TDD mode may only be controlled by the"
                                    " Sequencer. Enter the corresponding"
                                    " context to control TDD mode.")
        
        rts_address = self._acadia._firmware.rfdc_rts_regs.address().value()

        # Generate register writes for all the NCO updates that need to happen
        if nco_update_request != 0:
            for tile in range(8):
                if nco_update_enables[tile] != 0:
                    proc.bus_write(address=rts_address + 0x60 + tile,
                                    data=nco_update_enables[tile], 
                                    comment=f"Set update enable for tile {tile}")

            if nco_phase_reset != 0:
                proc.bus_write(address=rts_address + 0x68, 
                                data=nco_phase_reset,
                                comment="Set phase reset register")

            # Carry out the procedure for a synchronized update with SYSREF
            # We'll assume that the SYSREF is already being generated continuously

            # 1. Set dac0_sysref_int_gating high and pulse dac0_nco_update_req
            proc.bus_write(address=rts_address + 0x69, 
                            data=((1 << 8) | (1 << 0)),
                            comment="Set sysref_gating high and dac0_nco_update_req")
            proc.nop()
            proc.bus_write(address=rts_address + 0x69, 
                            data=(1 << 8),
                            comment="Clear dac0_nco_update_req")

            # 2. Wait until dac0_nco_update_busy[1] goes high, indicating that
            #    SYSREF has been properly gated
            with proc.repeat_until(proc.bus_read(rts_address) & (1 << 1) != 0):
                pass

            # 3. Pulse the rest of the nco_update_req signals if necessary
            #    (and make sure to keep dac0_sysref_int_gating high)
            if (nco_update_request & ~(1 << 0)) != 0:
                proc.bus_write(address=rts_address + 0x69, 
                            data=((1 << 8) | nco_update_request),
                            comment="Set the other nco_update_req signals")
                proc.nop()
                proc.bus_write(address=rts_address + 0x69, 
                                data=(1 << 8),
                                comment="Clear the other nco_update_req signals")

            # 4. Wait until all the busy outputs (except for dac0_nco_update_busy[1])
            #    are low
            m = 0xFFFF & ~(1 << 1)
            with proc.repeat_until(proc.bus_read(rts_address) & m == 0):
                pass

            # 5. Re-enable SYSREF by pulsing dac0_sysref_int_reenable
            proc.bus_write(address=rts_address + 0x69, 
                            data=((1 << 9)|(1 << 8)),
                            comment="Set dac0_sysref_int_reenable")
            proc.nop()
            proc.bus_write(address=rts_address + 0x69, 
                            data=(1 << 8),
                            comment="Clear dac0_sysref_int_reenable")

            # 6. Wait until dac0_nco_update_busy[1] goes low
            with proc.repeat_until(proc.bus_read(rts_address) & 0xFFFF == 0):
                pass

            # Do we ever need to set dac0_nco_sysref_int_gating low? If so, do it here
            proc.bus_write(address=rts_address + 0x69, 
                            data=0,
                            comment="Clear sysref_gating")

            if self._nco_pl_event:
                # Write the PL event register
                # The bit pattern is the same as for the update request register
                # and the blocks we want to drive events for will be the same
                # Pulse it for one cycle
                proc.bus_write(address=rts_address + 0x6C, 
                                data=nco_update_request,
                                comment="Set the pl_event register")
                proc.nop()
                proc.bus_write(address=rts_address + 0x6C, 
                                data=0,
                                comment="Clear the pl_event register")

        # Write any DSA updates
        for i in range(4):
            if vop_dsa_update_reg & (1 << (16+i)):
                proc.bus_write(address=rts_address + 0x80, 
                                data=tile_dsa_codes[i],
                                comment=f"Set DSA register for tile {i}")

        # Update VOP if necessary
        if vop_dsa_update_reg != 0:
            proc.bus_write(address=rts_address + 0x6D, 
                            data=vop_dsa_update_reg,
                            comment=f"Set VOP/DSA update register")

        if tdd_mode_set_reg != 0:
            proc.bus_write(address=rts_address + 0x6B, 
                            data=tdd_mode_set_reg,
                            comment="Write TDD mode set register")
        if tdd_mode_clear_reg != 0:
            proc.bus_write(address=rts_address + 0x6C, 
                            data=tdd_mode_clear_reg,
                            comment="Write TDD mode clear register")
            
        super().__exit__(exc_type, exc_val, exc_tb)
        
@dataclass
class StreamConfiguration:
    """
    An abstraction for configurations of the stream processing path.
    """
    
    input_source: object
    module: str 
    input_resource: object
    module_resource: object
    adc_switch_master: int
    adc_switch_slave: int
    input_switch_master: int
    input_switch_slave: int
    
    def output_datamover(self):
        return f"module{self.input_switch_slave}_s2mm_datamover"
    
class Acadia:
    """
    A class that implements system-wide commands for the Acadia hardware.
    """
    
    CMACC_QUADRANT_1 = 0
    CMACC_QUADRANT_2 = 1 << 19
    CMACC_QUADRANT_3 = (1 << 19) | (1 << 20)
    CMACC_QUADRANT_4 = 1 << 20
    
    def requires_sequencer(func):
        """
        A decorator for functions in the :class:`Acadia` class that must be 
        called in the context of a :class:`Sequencer`\.

        :param func: Function to wrap
        :type func: callable
        """

        @wraps(func)
        def _wrapped(acadia_self, *args, **kwargs):
            if acadia_self._active_sequencer is None:
                raise TypeError(f"Function {func.__name__} must be"
                                " called in the context of a sequencer.")
            return func(acadia_self, *args, **kwargs)
            
        return _wrapped
    
    def __init__(self, firmware=None):  
        self._firmware = Firmware(firmware if firmware is not None else CONFIG_200)
        
        def input_switch_port(res_self):
            return self._firmware.stream_inputs()[res_self.kind][res_self._resource_id]
        
        self._stream_input_resources = {k: ManagedResource(f"{k}StreamInput", 
                                                           (), 
                                                           {"kind": k, 
                                                            "switch_port": input_switch_port}, 
                                                           allocation_limit=len(v)) 
                                        for k,v in self._firmware.stream_inputs().items()}
        
        def module_switch_port(res_self):
            return self._firmware.stream_modules()[res_self.kind][res_self._resource_id]
        
        self._stream_module_resources = {k: ManagedResource(f"{k}Module", 
                                                           (), 
                                                           {"kind": k,
                                                            "switch_port": module_switch_port}, 
                                                           allocation_limit=len(v)) 
                                        for k,v in self._firmware.stream_modules().items()}
        
        self._stream_configurations = []
        
        # Create various Processors
        # Note that the Processors cannot be ManagedMemory (and therefore, have the
        # Processor objects keep track of their instruction memory usage) 
        # because when Instruction objects are requested, the number of native
        # instruction words that they'll compile into isn't know until ``compile``
        # is actually called, which only happens once all the Instruction
        # resources have been created
        self._sequencer_type = ManagedResource("Sequence", (Sequencer,), {})
                    
        # When we enter contexts, keep track of the active sequencer
        self._active_sequencer = None

        # Create a synchronizer for channel actions
        self.channel_synchronizer = DMASynchronizer(name="channel_synchronizer", allow_standalone=True)
        self.tile_synchronizer = RFDCSynchronizer(name="tile_synchronizer", allow_standalone=True)
        
        self._create_cache()
        self._create_dac_arrays()
        self._create_cmacc_kernel_arrays()
        self._create_pl_ddr_arrays()
        self._create_ps_ddr_arrays()
        self._create_ocm_arrays()
        self._create_zdma()
        self._create_channels()
        self._create_switches()       
        
    def attach(self):
        """
        Maps system memory and connects to hardware drivers.
        """

        self._mem_file = os.open("/dev/mem", os.O_SYNC | os.O_RDWR)
        self._mem_maps = []
        
        self._attach_resource(self.CacheArray)
        self._attach_resource(self.OCMArray)
        
        # Map instruction memory for all of the processors
        self._sequencer_instruction_memory = self._attach_memory(
            address=self._firmware["sequencer_instruction_memory"]["address"],
            size=self._firmware["sequencer_instruction_memory"]["size_bits"] // 8,
            return_map=True)  
        
        for dac_mem in self.DACArray:
            self._attach_resource(dac_mem)
            
        for cmacc_kernel_mem in self.CMACCKernelArray:
            self._attach_resource(cmacc_kernel_mem)
                
        self._attach_resource(self.PLDDR0Array)
        self._attach_resource(self.PLDDR1Array)
        self._attach_resource(self.PSDDRArray)
            
        # Connect to the RFDC driver and initialize
        rfdc.attach()
        utils.attach()
        RFClk.init(self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["clk104_spi0"])
        
        # Connect the switches
        self._ADC_input_switch.attach(self._attach_memory(
            address=self._firmware["stream_processing_path"]["adc_input_switch"]["axi_address"], 
            size=self._firmware["stream_processing_path"]["adc_input_switch"]["axi_size_bits"] // 8,
            dtype=np.uint32))
        
        self._stream_processing_path_input_switch.attach(self._attach_memory(
            address=self._firmware["stream_processing_path"]["input_switch"]["axi_address"], 
            size=self._firmware["stream_processing_path"]["input_switch"]["axi_size_bits"] // 8,
            dtype=np.uint32))
        
        # Connect to the PS GDMA
        for instance in self._ZDMA.instances:
            instance.attach(self._attach_memory(
                address=0xFD50_0000 + (instance._resource_id*0x1_0000),
                size=0x1_0000))
            
        # Connect to the GPIO registers and store sequencer bus addresses for the GPIO dataports
        self._psgpio_mem = self._attach_memory(0xFF0A0000, 0x400, dtype=np.uint32)
            
        # Configure and connect to the sysfs interface for various GPIO        
        self._sequencer_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["sequencer_run"]
        PSGPIO.sysfs_export(self._sequencer_gpio)
        PSGPIO.sysfs_set_direction(self._sequencer_gpio, "out")
        PSGPIO.sysfs_write(self._sequencer_gpio, 0)
        
        self._sequencer_nrst = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["sequencer_nrst"]
        PSGPIO.sysfs_export(self._sequencer_nrst)
        PSGPIO.sysfs_set_direction(self._sequencer_nrst, "out")
        PSGPIO.sysfs_write(self._sequencer_nrst, 0)

        self._ddr4_c0_sys_rst_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c0_sys_rst"]           
        PSGPIO.sysfs_export(self._ddr4_c0_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 0)

        self._ddr4_c1_sys_rst_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c1_sys_rst"]            
        PSGPIO.sysfs_export(self._ddr4_c1_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 0)

        self._ddr4_c0_cal_cplt_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c0_cal_cplt"]           
        PSGPIO.sysfs_export(self._ddr4_c0_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_cal_cplt_gpio, "in")

        self._ddr4_c1_cal_cplt_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c1_cal_cplt"]           
        PSGPIO.sysfs_export(self._ddr4_c1_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_cal_cplt_gpio, "in")

        self._clk_wiz_locked = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["clk_wiz_locked"]           
        PSGPIO.sysfs_export(self._clk_wiz_locked)
        PSGPIO.sysfs_set_direction(self._clk_wiz_locked, "in")
        
        self._sequencer_done = self._firmware["ps_gpio"]["sysfs_offset"] + 64           
        PSGPIO.sysfs_export(self._sequencer_done)
        PSGPIO.sysfs_set_direction(self._sequencer_done, "in")

        self._previous_run_time = 0
        
    def detach(self):
        """
        Unmaps all system memory.
        """

        for m in self._mem_maps:
            m.close()
            
            
    # ---------------- COMPILATION FUNCTIONS ---------------------- #
    
    def sequencer(self) -> Sequencer:
        """
        Create and store a new sequencer object associated with this system,
        if a sequencer is not already active (in which case, that one is 
        returned).
        """

        if self._active_sequencer is not None:
            return self._active_sequencer
        
        return self._sequencer_type()
    
    def sequence(self, func: Callable) -> Sequencer:
        """
        Compiles a Python function as a sequence for the Acadia sequencer. 
        The wrapped function should accept an instance of :class:`Acadia` as
        its sole argument.
        
        :param func: Function to be compiled as a Sequencer sequence.
        :type func: callable with one argument of type :class:`Sequencer`
        :return: A :class:`Sequencer` object containing the compiled sequence
        :rtype: :class:`Sequencer`
        """

        # Get a new sequence resource
        s = self.sequencer()
        
        # Drive the sequencer done pin low
        s.bus_write(address=self._firmware.sequencer_bus_decoder["ps_gpio5"].address(), data=0)
        
        # Store this particular Sequencer instance as an instance member of the 
        # Acadia object so that helper functions of the Acadia object know to 
        # use it
        self._active_sequencer = s
        
        # Call the function to populate the sequencer object and compile it
        with s:
            # Reset all the stream modules
            self.reset_all_streams()

            # Clear the stream offsets
            # Technically this isn't needed because resetting the streams resets 
            # the Datamover controller which clears the address offset register, 
            # but compiling in these instructions makes it easy to update them
            # for module_num,module in enumerate(self._firmware["stream_processing_path"]["modules"]):
            #     datamover_name = f"module{module_num}_s2mm_datamover_controller"
            #     bus_address_base = self._firmware.sequencer_bus_decoder[datamover_name].address().value()
            #     self._active_sequencer.bus_write(address=bus_address_base+3, 
            #                                     data=0,
            #                                     comment=f"Clear offset for"
            #                                             f" {datamover_name}"
            #                                             f" ({module['kind']})")

            retval = func(self)
            
        self._active_sequencer = None

        # Add one instruction buffer between the end of the program and completion reporting,
        # just for sanity (TODO maybe this isn't needed anymore?)
        s.nop()

        # Report to the PS that the sequencer is halted
        s.bus_write(address=self._firmware.sequencer_bus_decoder["ps_gpio5"].address(), data=1)

        s.halt()
        
        # Because the sequence resource object was created before we knew its 
        # size and because we know that the size won't change from this point,
        # we can update the size of the instance and the allocation index of
        # the sequence resource
        s.size = s.Instruction.usage()
        
        return retval
                        
    # -------------- CLOCKING AND SYNCHRONIZATION ROUTINES ----------- #
    
    def align_tile_latencies(self):
        """
        Align the latencies of all tiles by measuring the latency through
        all interface FIFOs. Delays are then applied so that the total latency
        of all tiles is equal to that of the slowest. This method uses the
        RFDC Multi-Tile Synchronization (MTS) routines.
        """

        # Initialize MTS data structures
        rfdc.mts_init()

        # Enable continuous SYSREF clock
        logger.debug("Enabling continuous SYSREF")
        self.pulse_sysref()

        # Carry out the synchronization
        logger.debug("Synchronizing...")
        result = rfdc.mts_sync()
        logger.debug("Synchronization completed")

        # Turn off SYSREF
        self.pulse_sysref(0)
        logger.debug("SYSREF disabled")

        utils.sys_nanosleep(200000000)

        return result
    
    def update_ncos_synchronized(self):
        """
        Synchronously update the frequency and/or phase of multiple NCOs 
        following a series of calls to :meth:`update_nco_frequency`, 
        :meth:`update_nco_phase`, and/or :meth:`reset_nco_phase`.

        Note that before calling this function, the tiles must be aligned by 
        calling ``self.align_tile_latencies`` and each channel passed in must 
        have had its NCO configured for synchronous updates by calling
        ``<channel>.configure_nco(update_source="sysref")``.
        """

        # Carry out a synchronized NCO update
        self.pulse_sysref(1)
            
        # Wait a moment so that the sysref will have actually happened
        # TODO: find a way to check this. if it exists it's not documented
        # until then, we'll sleep for just a bit; 5us seems nice
        utils.sys_nanosleep(5000)

    def update_nco_frequency(self, channel: Channel, frequency: float):
        """
        Update the NCO frequency. If called in a Sequencer context, this will
        update the RFDC through the bus; otherwise, it will be updated via a
        driver call.

        :param channel: Channel to update
        :type channel: :class:`Channel`
        :param frequency: Frequency in Hz
        :type frequency: float
        """     
        
        frequency_word = channel.frequency_to_nco_word(frequency)
        
        proc = Processor.active_processor()
        if proc is None:
            channel.set_nco_frequency_word(frequency_word)
                
        elif isinstance(proc, Sequencer):    
            frequency_base_reg = self._firmware.rfdc_rts_regs.address().value() + channel.num()*2
            
            if not channel.is_dac:
                frequency_base_reg += 16*2 
            proc.bus_write(address=frequency_base_reg, 
                            data=(frequency_word >> 16) & 0xFFFFFFFF,
                            comment="Write NCO frequency high bits")
            proc.bus_write(address=frequency_base_reg+1, 
                            data=frequency_word & 0xFFFF,
                            comment="Write NCO frequency low bits")

            self.tile_synchronizer.add({
                "function": RFDCSynchronizer.NCO_FREQUENCY, 
                "self": self, 
                "args": (channel,), 
                "kwargs": {},
                "retval": None})
        
        else:
            raise TypeError("NCO frequency can only be set in `Sequencer` contexts or on the PS.")
    
    def update_nco_phase(self, channel: Channel, phase: float):
        """
        Set the NCO phase offset to the given value.

        :param phase: Phase in radians
        :type phase: float
        """
        phase_word = channel.phase_to_nco_word(phase)
        proc = Processor.active_processor()
        if proc is None:
            channel.set_nco_phase_word(phase_word)
                
        elif isinstance(proc, Sequencer):
            phase_reg = self._firmware.rfdc_rts_regs.address().value() + 0x40 + channel.num()
            
            if not channel.is_dac:
                phase_reg += 16
                
            proc.bus_write(address=phase_reg, 
                           data=phase_word & 0x0003FFFF,
                           comment=f"Write to NCO phase register for {channel}")

            self.tile_synchronizer.add({
                "function": RFDCSynchronizer.NCO_PHASE, 
                "self": self, 
                "args": (channel,), 
                "kwargs": {},
                "retval": None})
            
        else:
            raise TypeError("NCO phase can only be set in `Sequencer` contexts or on the PS.")

    def reset_nco_phase(self, channel: Channel):
        """
        Reset the value of the NCO phase accumulator.
        """

        proc = Processor.active_processor()
        if proc is None:
            channel.reset_nco_phase()
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will set the bit in the register
            self.tile_synchronizer.add({
                "function": RFDCSynchronizer.NCO_PHASE_RESET, 
                "self": self, 
                "args": (channel,), 
                "kwargs": {},
                "retval": None})
            
        else:
            raise TypeError("NCO accumulator phase can only be reset in"
                            " `PythonProcessor` or `Sequencer` contexts.")
    
    def configure_clocks(self, reference="internal"):
        """
        Configures the system clocks. Note that the clocking system will be
        reset and phase relationships among clocks may be reset. Additionally,
        clock dividers and SYSREF divider are synchronized as per the
        requirements for JESD204B (procedure adapted from TI datasheet for
        LMK04828).
        """           

        # Calculate the divider value that we need for the LMK output channels
        # VCO is configured for 3 GHz
        target_frequency = self._firmware["clk104_pl_clk"]["freq_hz"]
        divider = 3e9 / target_frequency
        if round(divider, 6) != round(divider):
            raise ValueError(f"Required frequency {target_frequency} does not"
                " divide the LMK VCO frequency by an integer.")
        divider = int(round(divider))

        # Reset chip and load a default config
        RFClk.LMK.reset()
        RFClk.LMK.set_config()

        # Set reference source
        RFClk.LMK.set_input(0 if reference == "external" else 1)

        # Configure manual SYNC
        RFClk.LMK.set_sync_polarity(False)
        RFClk.LMK.set_sync_mode(1)
        RFClk.LMK.set_sysref_mux(0)

        # Set DCLK output dividers to generate all of the clocks at the PL clock rate and prepare for SYNC
        # Although the regular channel (non-sync) for the sync channel SDCLK_RFDC
        # isn't connected to anything, it needs to be set up in order for the
        # sync signal to be generated
        for output in [RFClk.LMK.DCLK_PL, 
                       RFClk.LMK.DCLK_RFDC_DAC, 
                       RFClk.LMK.DCLK_RFDC_ADC,
                       RFClk.LMK.SDCLK_RFDC-1]:
            # Set all output multiplexers to the input for the divider
            # with duty cycle correction and half-step
            RFClk.LMK.set_output_mux(output, 1)
            RFClk.LMK.set_output_divider(output, divider)
        
            # Power up parts of the output chain
            RFClk.LMK.set_output_powerdown_state(output,
                                        disable_output=False, 
                                        disable_digital_delay=False, 
                                        disable_glitchless_halfstep=True,
                                        disable_analog_delay_glitchless=True,
                                        disable_analog_delay=True,
                                        disable_sdclk=False)
            
            # Allow the output to be synchronized
            RFClk.LMK.set_output_divider_synchronization_disable(output, False)
            
        # Enable SYNC
        RFClk.LMK.set_sync_enabled(True)

        # Set SYSREF clk to 10 MHz and power up
        RFClk.LMK.set_sysref_divider(300)
        RFClk.LMK.set_sysref_power_state(False)
        RFClk.LMK.set_sysref_digital_delay_power_state(False)
        RFClk.LMK.set_sysref_pulser_power_state(False)
        RFClk.LMK.set_sysref_global_power_state(False)

        # Configure SYSREF to allow synchronization
        RFClk.LMK.set_sysref_divider_synchronization_disable(False)

        # Configure the pulser to generate one pulse. Note: TI procedure uses
        # 2 pulses but this doesn't seem necessary, and if it's really needed
        # then that would mean you're not certain which edge actually performs
        # the reset - I guess we'll see if this ends up being necessary...
        RFClk.LMK.set_sysref_pulse_count(1)

        # Clear the SYSREF digital delay shift register
        RFClk.LMK.set_sysref_clr(True)

        # Set all the digital delay counts (DCLKoutx_DDLY_CNTH/L, SYSREF_DDLY,
        # SDCLKoutx_DDLY)
        # We won't change the default settings, any adjustment to the default
        # delays should be done here

        # Perform the sync by toggling SYNC_POL
        RFClk.LMK.set_sync_polarity(True)
        utils.sys_nanosleep(1000000)
        RFClk.LMK.set_sync_polarity(False)

        # Now that everything is sync'ed, disable synchronization on the 
        # dividers so that future SYNC pulses don't reset them
        RFClk.LMK.set_sysref_divider_synchronization_disable(True)
        for output in [RFClk.LMK.DCLK_PL, 
                       RFClk.LMK.DCLK_RFDC_DAC, 
                       RFClk.LMK.DCLK_RFDC_ADC]:
            RFClk.LMK.set_output_divider_synchronization_disable(output, True)

        # Release the reset for the SYSREF digital delay
        RFClk.LMK.set_sysref_clr(False)

        # Configure SYSREF in pulser mode
        # SYNC_MODE=3: SYNC generated by pulser when writing to the SYSREF
        #              pulse count register
        RFClk.LMK.set_sync_mode(3) 

        # Configure the SYSREF_MUX so that the SYSREF pulser drives the 
        # SYSREF/SYNC path 
        RFClk.LMK.set_sysref_mux(2) 

        # Wait a bit for everything to lock
        utils.sys_nanosleep(500000000)

    def pulse_sysref(self, count=None):
        """
        Pulse the SYSREF of the LMK04828 a given number of times. 
        Valid values for ``count`` are:

        - ``None``: SYSREF_MUX is set so that the SYSREF/SYNC path is driven
            continuously by the SYSREF clock
        - ``0``: SYSREF_MUX is set so that the SYSREF/SYNC path is driven by the
            pulser.
        - ``1, 2, 4, 8``: SYSREF_PULSE_CNT is programmed to produce the given 
            number of pulses
        """

        if count is None:
            RFClk.LMK.set_sysref_mux(3)
        elif count == 0:
            RFClk.LMK.set_sysref_mux(2)
        elif count == 1 or count == 2 or count == 4 or count == 8:
            RFClk.LMK.set_sysref_pulse_count(count)
        else:
            raise ValueError(f"Invalid SYSREF pulse setting {count}.")
        
    def get_clock_status(self, clkin=10e6):
        """
        :param clkin: Frequency of clock provided to CLK104 module in Hz
        :type clkin: float
        :return: A dictionary containing various clocking system parameters.
        """

        d = {}
        d["clock_source"] = "external" if RFClk.LMK.get_input() == 0 else "internal"
        d["PLL1_N"] = RFClk.LMK.get_PLL1_N()
        d["input_R"] = RFClk.LMK.get_input_R(RFClk.LMK.get_input())
        d["PLL2_P"] = RFClk.LMK.get_PLL2_P()
        d["PLL2_N"] = RFClk.LMK.get_PLL2_N()
        d["PLL2_R"] = RFClk.LMK.get_PLL2_R()
        d["PLL1_out_frequency"] = clkin * d["PLL1_N"] / d["input_R"]
        d["PLL2_out_frequency"] = d["PLL1_out_frequency"] * d["PLL2_P"] * d["PLL2_N"] / d["PLL2_R"]

        # SYSREF
        d["SYSREF_power_state"] = RFClk.LMK.get_sysref_power_state()
        d["SYSREF_digital_delay_power_state"] = RFClk.LMK.get_sysref_digital_delay_power_state()
        d["SYSREF_global_power_state"] = RFClk.LMK.get_sysref_global_power_state()
        d["SYSREF_pulser_power_state"] = RFClk.LMK.get_sysref_pulser_power_state()
        d["SYSREF_divider"] = RFClk.LMK.get_sysref_divider()
        d["SYSREF_divider_sync_disabled"] = RFClk.LMK.get_sysref_divider_synchronization_disable()
        d["SYSREF_digital_delay"] = RFClk.LMK.get_sysref_digital_delay()
        d["SYSREF_mux"] = RFClk.LMK.get_sysref_mux()
        d["SYSREF_clr"] = RFClk.LMK.get_sysref_clr()
        
        # SYNC 
        d["SYNC_MODE"] = RFClk.LMK.get_sync_mode()
        d["SYNC_POL"] = RFClk.LMK.get_sync_polarity()
        d["SYNC_EN"] = RFClk.LMK.get_sync_enabled()

        # DCLKout information
        for channel,name in [(RFClk.LMK.DCLK_PL,"PL"), 
                             (RFClk.LMK.DCLK_RFDC_ADC, "ADC_ref"), 
                             (RFClk.LMK.DCLK_RFDC_DAC, "DAC_ref"), 
                             (RFClk.LMK.DCLK_LMX_ADC, "ADC_LMX"), 
                             (RFClk.LMK.DCLK_LMX_DAC, "DAC_LMX"),
                             (RFClk.LMK.SDCLK_RFDC-1, "RFDC")]:
            # Settings shared by the channel and its SDClk
            pd = RFClk.LMK.get_output_powerdown_state(channel)
            d[f"{name}_digital_delay_powerdown"] = bool(pd & (1 << 7))
            d[f"{name}_digital_glitchless_halfstep_powerdown"] = bool(pd & (1 << 6))
            d[f"{name}_analog_glitchless_halfstep_powerdown"] = bool(pd & (1 << 5))
            d[f"{name}_analog_delay_powerdown"] = bool(pd & (1 << 4))
            d[f"{name}_IDL"] = RFClk.LMK.get_input_drive_level_increased(channel)
            d[f"{name}_ODL"] = RFClk.LMK.get_output_drive_level_increased(channel)

            # DCLK channel settings
            d[f"{name}_dclkout_powerdown"] = bool(pd & (1 << 3))
            d[f"{name}_dclk_divider"] = RFClk.LMK.get_output_divider(channel)
            d[f"{name}_dclk_frequency"] = d["PLL2_out_frequency"] / d[f"{name}_dclk_divider"]
            drive = RFClk.LMK.get_drive(channel)
            d[f"{name}_dclk_drive"] = f"{drive} ({RFClk.LMK.drive_to_string(drive)})"
            d[f"{name}_dclk_mux"] = RFClk.LMK.get_output_mux(channel)
            d[f"{name}_dclk_analog_delay"] = RFClk.LMK.get_output_analog_delay(channel)
            d[f"{name}_dclk_digital_delay"] = RFClk.LMK.get_output_digital_delay(channel)
            d[f"{name}_dclk_sync_disabled"] = RFClk.LMK.get_output_divider_synchronization_disable(channel)
            
            # SDCLK channel settings
            d[f"{name}_sdclkout_powerdown"] = bool(pd & (1 << 0))
            d[f"{name}_sdclkout_analog_delay_enabled"] = RFClk.LMK.get_sdclk_analog_delay_enabled(channel+1)
            drive = RFClk.LMK.get_drive(channel+1)
            d[f"{name}_sdclk_drive"] = f"{drive} ({RFClk.LMK.drive_to_string(drive)})"
            d[f"{name}_sdclk_mux"] = RFClk.LMK.get_sdclk_mux(channel+1)
            d[f"{name}_sdclk_analog_delay"] = RFClk.LMK.get_sdclk_analog_delay(channel+1)
            d[f"{name}_sdclk_digital_delay"] = RFClk.LMK.get_sdclk_digital_delay(channel+1)
            
        d["clk_wiz_locked"] = PSGPIO.sysfs_read(self._clk_wiz_locked)
                        
        return d

    def sequencer_clock_frequency(self) -> float:
        """
        :return: The clock frequency of the sequencer (and correspondingly 
            the frequency of the RF tile interface) in Hz
        :rtype: float
        """
        return self._firmware["clk104_pl_clk"]["freq_hz"]

    def seconds_to_cycles(self, 
                        t: Union[float, np.ndarray], 
                        rounding_raise: bool = True, 
                        eps: float = 1e-6) -> Union[np.int32, np.ndarray]:
        """
        Convert a float or array of floats into integer numbers of sequencer cycles.
        The parameter ``rounding_raise` determines the behavior when a provided time 
        does not equal an integer number of cycles exactly. When ``True``,
        an exception is raised if any number of calculated cycles is more than 
        ``eps`` away from the nearest integer. When ``False``, 
        all values are blindly rounded to the nearest integer.
        """

        input_type = t.dtype if isinstance(t, np.ndarray) else type(t)

        if not np.issubdtype(input_type, float):
            raise TypeError(f"Input to seconds_to_cycles must be a float or numpy array of floats;"
                            f" received {input_type}")

        cycles = t * self.sequencer_clock_frequency()
        rounded = np.rint(cycles).astype(np.uint32)
        
        if rounding_raise:
            violating_indices = np.argwhere(np.abs(rounded - cycles) > eps)
            if violating_indices.shape[0] > 0:
                if isinstance(t, float):
                    raise ValueError(f"The following value does not equate to an integer number of cycles:"
                                    f" {t} (cycles: {cycles})")
                else:
                    violating_values = [t[tuple(violating_indices[i,:])] for i in range(violating_indices.shape[0])]
                    violating_cycles = [cycles[tuple(violating_indices[i,:])] for i in range(violating_indices.shape[0])]
                    violating_strings = [f"{v} ({c} cycles)" for v,c in zip(violating_values, violating_cycles)]
                    raise ValueError(f"The following values do not equate to an integer number of cycles:"
                                    f" {', '.join(violating_strings)}")

        return rounded

    def delay_times_to_counter_values(self, 
                                    t: np.ndarray, 
                                    waveform_memory: Union[WaveformMemory, None] = None,
                                    waveform_channel: Union[Channel, str, None] = None) -> np.ndarray:
        """
        Calculates counter values for sequencer DSPs for the design pattern of 
        loading the DSP with a counter value, playing a waveform, waiting some 
        amount by starting the DSP decrementing and waiting for it to reach 
        zero, and then playing another waveform.
        After converting to cycles, the time values need to be offset to account 
        for the overhead of configuring the DSP and the synchronizer(s), so this
        function computes the values that should be loaded into the DSP. 

        If the sequence involves playing a second pulse on the same channel once 
        the delay is complete, there is a minimum time in between the first 
        pulse finishing and the second pulse starting so that the DMA has ample
        time to retrieve the descriptor for the second pulse. This requires that 
        the command to the DMA be pushed into the FIFO after it stops running, and
        then with the 4 cycles of retrieval time, the minimum delay is 5 cycles.

        This minimum delay only applies if the second pulse is on the same channel
        and if the delay amount is comparable to the length of the first pulse; if
        the second pulse is far in the future, on another channel, or is 
        non-existent, this condition may be safely ignored. However, this condition
        may be automatically checked by providing the waveform memory for the first
        pulse in the ``waveform_memory`` parameter and the channel it's played on in
        the ``waveform_channel`` parameter.
        """

        # We need to take into account the few-cycle overhead associated with 
        # the counter and synchronizers
        # From system calibrations using very short pulses, we know that using a 
        # delay count of 2 yields a 60 ns interval between the starting points 
        # of the two pulses, and that this is the minimum counter value we can 
        # use. 

        # First, convert all the time values into cycles
        delay_cycles = self.seconds_to_cycles(t)

        # TODO: Confirm this number still applies as of v8, it's likely shorter now
        # Subtract off the 50 ns (10 cycle) offset, so that a delay of 60 ns 
        # corresponds to a count value of 2
        dsp_count_values = delay_cycles - 10 
        amin = np.argmin(dsp_count_values)
        if dsp_count_values[amin] < 2:
            raise ValueError(f"Counter value {dsp_count_values[amin]}"
                            f" for time {t[amin]} is too small")

        # Now, we need to make sure that the delay is long enough so that the 
        # second pulse starts at least 5 cycles after the first one
        # We can do this by comparing the length of the delay to the length
        # of the first pulse, and if the length of the delay is longer than
        # the length of the pulse + 5, we don't have to do anything
        # If there's no second pulse on this channel or it's known to start 
        # way in the future, this can be omitted
        if waveform_memory is None:
            if waveform_channel is not None:
                raise ValueError(f"waveform_channel must be None if waveform_memory is None.")
        else:
            if waveform_channel is None:
                raise ValueError(f"Must provide waveform channel when calculating waveform memory length in cycles.")

            waveform_length_cycles = waveform_memory.nbytes // waveform_channel.interface_width_bytes

            # TODO: Confirm that this still applies for v8, it's likely shorter now
            if delay_cycles[amin] < waveform_length_cycles + 5:
                raise ValueError(f"Delay is too short for separating two waveforms on"
                                f" the same channel using a dynamic delay; first"
                                f" waveform is {waveform_length_cycles} cycles,"
                                f" but requested a delay of {delay_cycles[amin]}")

        return dsp_count_values

    # -------------- CHANNEL HELPERS ----------- #

    def DAC(self, num: Union[int, str]) -> Channel:
        """
        :return: a :class:`Channel` representing a DAC.
        :rtype: :class:`Channel`
        """

        return self._DAC_channels[int(num)]

    def ADC(self, num: Union[int, str]) -> Channel:
        """
        :return: a :class:`Channel` representing an ADC.
        :rtype: :class:`Channel`
        """

        return self._ADC_channels[int(num)]
    
    def channel(self, specifier: Union[str, Channel, None]) -> Channel:
        """
        Obtain a channel object via a string specifier of the form "DACxx"
        or "ADCxx".
        """

        if specifier is None or isinstance(specifier, Channel):
            return specifier
        
        if not isinstance(specifier, str):
            raise TypeError(f"Channel specifier must be a string;"
                            f" received {specifier}")
        
        m = re.match("(ADC|DAC)([0-9]+)", specifier)
        if m is None:
            raise ValueError(f"Unable to parse channel specifier {specifier}")
        
        channel_type, num = m.groups()
        if channel_type == "ADC":
            return self.ADC(num)
        
        return self.DAC(num)
    
    # -------------- ABSTRACTIONS FOR JOINT PS-PL ROUTINES ----------- #

    @staticmethod
    def sequencer_dma_instruction_simplifier(instruction) -> bool:
        """
        This function should be provided as a simplifier function
        to any STP instructions that may need to be removed due to
        dwell optimization. At assembly time, this will check
        whether the imm2 field of the instruction evaluates to -1, and
        if so, it will return ``True`` to indicate that the instruction
        should be replaced with a NOP.
        """
        imm2 = instruction.imm2
        if (np.issubdtype(type(imm2), int) or isinstance(imm2, (np.uint32, np.int32))) and imm2 == -1:
            return True
        if isinstance(imm2, (Symbol, Operation)) and imm2.value() == -1:
            return True

        return False

    def waveform_dma_command(self, waveform: WaveformMemory) -> Union[int, Symbol, Operation]:
        """
        Create the command word which, when issued to a DMA, will play the 
        provided waveform.

        :type waveform: WaveformMemory
        """

        if not isinstance(waveform, WaveformMemory):
            raise TypeError(f"Waveform must be of type WaveformMemory;"
                            f" received type {type(waveform)}")

        if type(waveform._resource) not in self.DACArray:
            raise TypeError(f"Waveform commands may only be generated for waveforms"
                            f" located in DAC waveform memory")

        channel = None
        for idx,array_type in enumerate(self.DACArray):
            if type(waveform._resource) == array_type:
                channel = self.DAC(idx)
                break

        if channel is None:
            raise ValueError(f"Could not locate channel type; something weird happened.")

        word_address = waveform._resource._resource_id // channel.interface_width_bytes
        length_cycles = waveform.nbytes // channel.interface_width_bytes
        command = (word_address << 16) | (length_cycles - 1)

        return command

    @requires_sequencer
    def command_dma(self, 
                    channel: Channel, 
                    command_type: Literal[0,1,2,3,"continued arbitrary","arbitrary","continued constant","dwell"] = "arbitrary",
                    **kwargs) -> None:
        """
        Command a channel's DMA. The DMA has four different commands that it can process, 
        as provided by the ``command_type`` argument:

            - "continued arbitrary" instructs the DMA to increment its address register 
                for a given number of cycles. The initial address value is the current 
                value in the DMA's address register, allowing it to "continue" from a 
                previous command.
            - "arbitrary" instructs the DMA to first update its address register to a given value and 
                then increment its address output for a given number of cycles.
            - "continued constant" instructs the DMA to produce valid address outputs for a 
                given number of cycles without incrementing its address, creating a stream of 
                values at a constant address. The address used is the current value of the DMA
                address register.
            - "dwell" instructs the DMA to idle for a given number of cycles without 
                producing any valid output, acting effectively as a delay between 
                entries in the DMA FIFO.

        The arguments to the command depend on its type (when the "command" keyword is 
        not provided; see below for corresponding syntax). For "arbitrary" commands, 
        the keywords "address" and "length" must be provided. For all other commands, 
        "length" must be provided. The presence of any other keyword arguments than what
        the command requires raises an error.

        When the keyword "length" is provided, one may optionally specify a keyword 
        argument "length_is_minus_one"; if ``True``, the value of the "length" argument will be
        interpreted as containing one less than the true length of the command. This is 
        particularly useful for length arguments originating from real-time sources, such as cache, so
        as to not require the sequencer to subtract one before issuing the DMA command.

        As an alternative to the above keyword protocol, one may provide the raw value 
        to be written to the DMA register by providing
        the "command" keyword. When provided, the corresponding value is directly written to the DMA register
        for the provided command type with no further processing. The format of the 
        command argument depends on the command type:

            - For a "continued arbitrary" command, this is a 16-bit length in cycles. 
            
            - For an "arbitrary" command, the lower 16 bits are a length in cycles 
                and the upper 16 bits are a memory address in cycles.
            
            - For a "continued constant" command, this is a 32-bit length in cycles.
            
            - For a "dwell" command, this is a 32-bit length in cycles.

        :param channel: Physical channel to command.
        :type channel: :class:`Channel` or str
        :param command_type: Type of command to issue to the DMA.
        "type command_type: str or int
        """

        channel = self.channel(channel)

        # Determine the command type
        if np.issubdtype(type(command_type), int) or isinstance(command_type, (np.uint32, np.int32)):
            if command_type not in [0,1,2,3]:
                raise ValueError(f"Invalid command type specifier: {command_type}")
        elif isinstance(command_type, str):
            if command_type == 'continued arbitrary':
                command_type = 0
            elif command_type == 'arbitrary':
                command_type = 1
            elif command_type == 'continued constant':
                command_type = 2
            elif command_type == 'dwell':
                command_type = 3
            else:
                raise ValueError(f"Invalid command type specifier: {command_type}")
        else:
            raise TypeError(f"Command type specifier for command_dma must either be"
                            f" str or int; received {type(command_type)}")

        # Parse keyword arguments
        # When "command" is provided, we can just write to the DMA regardless of what
        # command type it is
        if "command" in kwargs:
            if len(kwargs) != 1:
                raise KeyError(f"When \"command\" is specified as an argument to"
                                f" ``command_dma``, no others may be. Found keywords"
                                f" {list(kwargs.keys())}")
            command = kwargs["command"]
        else:
            # Arbitrary command, try to extract both required arguments
            if command_type == 1:
                if "address" not in kwargs:
                    raise KeyError(f"Address must be provided for arbitrary DMA command.")
                address = kwargs.pop("address")

            if "length" not in kwargs:
                raise KeyError(f"Length must be provided for DMA command.")

            length_is_minus_one = kwargs.pop("length_is_minus_one", False)

            if len(kwargs) != 1:
                raise KeyError(f"Extra keyword arguments found for command_dma: {list(kwargs.keys())}")

            length_minus_one = kwargs["length"] if length_is_minus_one else kwargs["length"]-1
            if command_type == 1:
                command = (address << 16) | length_minus_one
            else:
                command = length_minus_one
            
    
        dev_name = f'{"dac" if channel.is_dac else "adc"}{channel.num()}_dma'
        device = self._firmware.sequencer_bus_decoder[dev_name]

        if np.issubdtype(type(command), int) or isinstance(command, (np.uint32, np.int32)):
            command_string = f"{command:08X}"
        elif (isinstance(command, Symbol) and command.assigned) or (isinstance(command, Operation) and command.resolveable()):
            command_string = f"{command.value()} (resolved from {command})"
        else:
            command_string = f"{command}"

        self._active_sequencer.bus_write(
            address=device.address().value() + command_type,
            data=command, 
            simplifier=Acadia.sequencer_dma_instruction_simplifier,
            comment=f"Command DMA for {channel}, type {command_type}: {command_string}")
            
    def memory_region(self, 
                      specifier: Union[Channel, ManagedMemory, np.ndarray, str, StreamConfiguration, None]) -> callable:
        """
        Retrieve a memory region for this instance from a specifier object. The
        returned object will always be a callable that can accept the arguments 
        "shape" and "dtype" in order to allocate memory in the desired region.
        
        Valid options for ``specifier`` and the corresponding returned regions 
        are:

        - A :class:`Channel` object for a DAC: The waveform memory allocator 
            for that channel is returned.

        - A :class:`StreamConfiguration` for a CMACC module: The kernel memory
            for that CMACC module is returned.

        - A string of the form ``"DACxx"``: The waveform memory allocator for that
            channel is returned.

        - ``"plddr"`` or ``"plddr0"``: The memory allocator for channel 0 of
            the PL DDR is returned.

        - ``"plddr1"``: The memory allocator for channel 1 of the PL DDR is 
            returned.

        - ``"cache"``: The memory allocator for the sequencer-PS shared cache
            is returned.

        - ``"ocm"``: The memory allocator for the region of PS on-chip memory
            (OCM) is returned.

        - ``"numpy"``: An allocator that creates a numpy array in the memory
            space of the running process is returned.
        """
        if specifier is None or isinstance(specifier, (ManagedMemory, np.ndarray)):
            return specifier
        
        if isinstance(specifier, Channel) and specifier.is_dac:
            return self.DACArray[specifier.num()]
        
        if isinstance(specifier, StreamConfiguration) and specifier.module == "cmacc":
            return self.CMACCKernelArray[specifier.module_resource._resource_id]
        
        if not isinstance(specifier, str):
            raise TypeError(f"Unable to convert object into memory region: {specifier}")
        
        # Check whether it's a string of a channel
        m = re.match("DAC([0-9]+)", specifier)
        if m is not None:
            channel_num = int(m.groups()[0])
            return self.DACArray[channel_num]
        
        s = str.lower(specifier)
        
        if s == "plddr0" or s == "plddr":
            return self.PLDDR0Array
        
        if s == "plddr1":
            return self.PLDDR1Array
        
        if s == "cache":
            return self.CacheArray
        
        if s == "ocm":
            return self.OCMArray
        
        if s == "numpy":
            return np.empty
        
        raise ValueError(f"Unable to parse memory region specifier string: {specifier}")
    
    def create_waveform_memory(self,
                        channel: Channel,
                        length: Union[int, float, np.ndarray] = None,
                        decimation: int = 1,
                        multiplicity: int = None,
                        region: Union[Channel, ManagedMemory, None, str] = None) -> WaveformMemory:
        """
        Allocate a waveform. This function allows for a few different signatures; 
        the first argument is always a :class:`Channel` object. 
        argument ``length`` determines the required signature:

        - If a ``float``, this should contain the length
            of the waveform in seconds. The corresponding amount of memory will
            be allocated, and potentially reduced by a decimation factor 
            (if provided). Decimation is not allowed for DAC channels.

        - If a numpy array with a complex or float dtype, the waveform is 
            allocated so that the data in the array could be stored after 
            being converted to samples. The shape of the resulting waveform 
            is chosen to match the argument. Decimation may not be provided.

        - If a numpy array with an integer dtype, the argument is assumed to
            contain the sample data that will eventually be stored in the 
            waveform. The last dimension of the array must be of length 2.
            Note that this does not store the sample data in any way; it just
            uses it to determine the shape of aray must be allocated. 
            Decimation may not be provided.

        - If ``None``, then a single sample for a decimated waveform is created.
            ``decimation`` must be set to 0.

        An optional multiplicity may be provided as either an int or a tuple,
        in which case the waveform will be created as a multidimensional array 
        with additional dimensions given by the multiplicity. The innermost
        dimension(s) are still determined by the provided input as described above.
             
        :param channel: Channel for the waveform
        :type channel: :class:`Channel`
        :param length: The length of the waveform; see description above
        :type length: float, np.ndarray
        :param decimation: Decimation for ADC waveforms
        :type decimation: int
        :param region: The memory region in which the WaveformMemory is stored
        """
        #################################################################
        # Start by validating the provided parameters
        #################################################################

        channel = self.channel(channel)

        # The region must be determined here
        region = self.memory_region(region)

        # If we couldn't determine the region from the provided parameter
        # and the channel is a DAC, try again to get the channel's dedicated
        # waveform memory region
        if region is None and channel.is_dac:
            region = self.memory_region(channel)

        # By this point we need to have determined a region, so throw an
        # error if we couldn't
        if region is None:    
            raise ValueError(f"Unable to determine memory allocation region.")
        
        if decimation is None:
            decimation = 1
        elif np.issubdtype(type(decimation), int) or (np.issubdtype(type(decimation), float) and round(decimation) == round(decimation, 1)):
            decimation = int(round(decimation))
        else:
            raise TypeError(f"Decimation must be an integer;"
                                    f" received {decimation}")
        
        if channel.is_dac and decimation != 1:
            raise ValueError(f"Decimation must be 1 for DAC channels.")
        
        if decimation != 1 and decimation % 4 != 0:
            raise ValueError(f"Decimation may only be 0, 1, or a multiple of 4"
                             f" (received {decimation})")

        dtype = "<i2" if decimation == 1 else "<i4"

        ##############################################################################
        # Convert provided lengths in time units into sample lengths and memory sizes
        ##############################################################################

        # Figure out how many samples will be processed at the channel interface
        if channel.is_dac:
            # All channels use 32 bits per sample at the FIFO, so we can infer this directly from the tile config
            channel_samples_per_cycle = self._firmware["rfdc"]["dac"]["channel_interface_width"][channel.num()] // 32
        else:
            # The source is either an ADC channel or a location in memory,
            # both of which must have interface widths equal to the path width
            channel_samples_per_cycle = self._firmware["stream_processing_path"]["width"] // 32

        if length is None:
            if decimation != 0:
                raise ValueError(f"Decimation must be 0 when length is None (found {decimation})")
            
            shape = 1
            logger.debug(f"Allocating single decimated sample for channel {channel}")

        elif np.issubdtype(type(length), float):
            # Length of waveforms in seconds
            if length <= 0:
                raise ValueError(f"Length of a waveform must be positive (received {length})")
            
            length_cycles = self.seconds_to_cycles(length)

            # The number of samples either entering or exiting the channel's FIFO
            channel_samples = length_cycles * channel_samples_per_cycle

            if channel.is_dac:
                shape = channel_samples
                logger.debug(f"Converted waveform for {channel} with length {length} seconds"
                        f" into {shape} samples ({length_cycles} cycles "
                        f" * {channel_samples_per_cycle} samples per cycle")

            else:
                if decimation == 0:
                    decimation = channel_samples

                elif channel_samples % decimation != 0:
                    raise ValueError(f"Number of input samples ({channel_samples})"
                                    f" is not a multiple of the decimation ({decimation}) ")
                
                shape = channel_samples // decimation
                
                logger.debug(f"Converted waveform for {channel} with length {length} seconds"
                            f" into {shape} samples ({length_cycles} cycles"
                            f" * {channel_samples_per_cycle} input samples per cycle"
                            f" // {decimation} input samples per output sample)")

        elif isinstance(length, np.ndarray):
            # When decimation is not 1, we don't have enough information to determine
            # how long in time the waveform is
            if decimation != 1:
                raise ValueError(f"When specifying a waveform size with a numpy"
                                 f" array, decimation must be 1.")

            if length.dtype.kind == 'f' or length.dtype.kind == 'c':
                # Convert float arrays to complex
                shape = length.shape

            elif length.dtype.kind == 'i':
                if length.shape[-1] != 2:
                    raise ValueError(f"WaveformMemory objects specified by numpy arrays must"
                                    f" have a shape in which the last dimension"
                                    f" is of length 2 (received array with shape"
                                    f" {length.shape})")

                # Because WaveformMemory objects automatically add the last dimension,
                # only include the shape up to that
                shape = shape[:-1]
            
            else:
                raise TypeError(f"WaveformMemory objects specified by numpy arrays must have"
                                f" float, complex, or integer dtypes (received"
                                f" dtype {length.dtype})")

            if shape[-1] % channel_samples_per_cycle != 0:
                raise ValueError(f"Number of waveform samples in last dimension of provided array"
                                f" (full shape {shape}) is not a multiple of the number of samples per"
                                f" cycle ({channel_samples_per_cycle}).")

        else:
            raise TypeError(f"WaveformMemory length must be specified as a float"
                            f" or as a numpy array (received type {type(length)}).")
        
        ############################################################################################
        # We now know the waveform time in cycles and size in samples, so create the waveform array
        ############################################################################################
        
        if np.issubdtype(multiplicity, np.integer):
            shape = (multiplicity, *shape)
        elif isinstance(multiplicity, tuple):
            shape = (*multiplicity, *shape)
        elif multiplicity is not None:
            raise TypeError(f"Multiplicity must be either an int or tuple;"
                            f" received type {type(multplicity)}")

        logger.debug(f"Allocating WaveformMemory with dtype {dtype} and shape"
                        f" {shape} samples")

        return WaveformMemory(shape=shape, dtype=dtype, resource_allocator=region)
        
    @requires_sequencer
    def schedule_waveform(self, 
                        waveform: WaveformMemory, 
                        channel: Union[Channel, str, None] = None,
                        stretch_length: Union[float, Symbol, Operation] = None,
                        stretch_length_is_minus_one: bool = False):
        """
        Schedule a waveform on a channel's DMA.

        For WaveformMemory objects allocated in a DAC channel's waveform memory,
        the channel to stream on may be inferred. However, because memory for
        ADC capture isn't bonded with a particular channel, the DMA to command
        cannot be inferred. Therefore, the channel must be specified explicitly.
        
        :param waveform: Signal to stream
        :type waveform: :class:`WaveformMemory`
        :param channel: Channel to stream
        :type channel: :class:`Channel`
        :param stretch_length: The amount by which to "stretch" the
            waveform. Stretching refers to playing the first half of a waveform,
            then repeating only the sample in the middle for some length of time,
            then playing the second half. This creates a "flat top" on the
            signal. When this is not ``None``, three DMA commands are generated,
            corresponding to the sequence described above. 
            
            In reality, the DMA doesn't repeat the sample in the middle, it 
            parks at the memory address in the middle of the waveform. Because the 
            waveform memory issues multiple samples per cycle, it is in fact a 
            sequence of a few samples that are repeated. It is assumed that the 
            waveform memory has been correctly populated so as to produce the 
            correct behavior.

            When a `float` is provided, this is the number of seconds by which to
            stretch the waveform (more accurately, this corresponds to the number
            of stretch cycles added). When a sequencer source is provided, no 
            conversion is performed; it is assumed that the source contains the 
            number of stretch cycles.
        :type stretch_length: float, Register, DSP
        :param stretch_length_is_minus_one: If ``True``, the provided length is understood 
            to be one less than the actual length to be included in the command. 
        :type stretch_length_is_minus_one: bool
        """
        if not isinstance(waveform, WaveformMemory):
            raise TypeError("Only waveforms associated with a channel may be scheduled.")

        if waveform._resource is None:
            raise ValueError("Cannot schedule waveform without resource.")

        if isinstance(channel, str):
            channel = self.channel(channel)

        if channel is None:
            # See if we can extract the channel from the waveform region
            if not isinstance(waveform._resource, tuple(self.DACArray)):
                raise TypeError("Waveforms to be scheduled for DAC channels must be located in DAC waveform memory.")

            channel = None
            for idx,t in enumerate(self.DACArray):
                if isinstance(waveform._resource, t):
                    channel = self.DAC(idx)
                    break
            
            if channel is None:
                raise TypeError(f"Something weird failed")

        elif isinstance(channel, Channel):
            # If we have a DAC channel, ensure that the waveform we're commanding
            # is in the correct region
            if channel.is_dac and not isinstance(waveform._resource, self.DACArray[channel.num()]):
                raise TypeError(f"Channel {channel} provided to schedule_waveform for a waveform"
                                f" located in {type(waveform._resource)}")
        else:
            raise TypeError(f"Received invalid type for channel: {type(channel)}")

        if not isinstance(stretch_length_is_minus_one, bool):
            raise TypeError(f"In schedule_waveform, stretch_length_is_minus_one must be a bool"
                            f" (received {type(stretch_length_is_minus_one)})")

        word_address = waveform._resource._resource_id // channel.interface_width_bytes
        length_cycles = waveform.nbytes // channel.interface_width_bytes

        if stretch_length is None:
            # Notify the synchronizer, which will add the DMA command for us
            self.channel_synchronizer.add({
                "function": DMASynchronizer.ARBITRARY, 
                "self": self, 
                "args": (), 
                "kwargs": {
                    "channel": channel, 
                    "length": length_cycles, 
                    "address": word_address},
                "retval": None})

            logger.debug(f"Scheduled arbitrary waveform on channel"
                         f" {channel} of length {length_cycles}"
                         f" at address {word_address}")

            return

        if np.issubdtype(type(stretch_length), float):
            stretch_length = self.seconds_to_cycles(stretch_length)
        elif isinstance(stretch_length, self.sequencer().Register):
            # Do nothing, registers can be passed directly into the synchronizer
            logger.debug(f"Adding indeterminate stretch length on channel {channel} from {stretch_length}")
        elif isinstance(stretch_length, self.sequencer().DSP):
            # Need to be more cautious, but is acceptable
            logger.warning(f"Scheduling stretch on channel {channel} from {length};"
                            f" ensure that the DSP is not automatically updating,"
                            f" as this can lead undefined behavior when the DSP"
                            f" value is reused during alignment.")
        elif isinstance(stretch_length, Symbol):
            if np.issubdtype(stretch_length.value_type(), float):
                stretch_length = Operation(Acadia.seconds_to_cycles, self, stretch_length)
            elif np.issubdtype(stretch_length.value_type(), int) or stretch_length.value_type() in [np.int32, np.uint32]:
                pass # We can just leave this as-is
            else:
                raise TypeError(f"Symbolic stretch length must use either"
                                f" int or float for a value type;"
                                f" found {stretch_length.value_type()}")
        elif isinstance(stretch_length, Operation):
            logger.debug(f"Found stretch length derived from an Operation;"
                        f" assuming that the result is in units of cycles.")
            # No further action required
        else:
            raise TypeError(f"Invalid type for stretch length: {type(stretch_length)}")

        self.channel_synchronizer.add({
            "function": DMASynchronizer.ARBITRARY, 
            "self": self, 
            "args": (), 
            "kwargs": {
                "channel": channel, 
                "length": length_cycles // 2, 
                "address": word_address},
            "retval": None})

        self.channel_synchronizer.add({
            "function": DMASynchronizer.CONSTANT_CONTINUED, 
            "self": self, 
            "args": (), 
            "kwargs": {
                "channel": channel, 
                "length": stretch_length,
                "length_is_minus_one": stretch_length_is_minus_one},
            "retval": None})

        # If the waveform has an odd number of samples, then the second arbitrary
        # part will be the same length as the first arbitrary part, and is equal to
        # (length_cycles - 1) / 2 = length_cycles // 2 = (length_cycles - 1) // 2 
        # (these equalties are only valid because length_cycles is odd)
        # If it has an even number of samples, then the second arbitrary part
        # has one less sample than the first, and is equal to 
        # (length_cycles // 2) - 1 = (length_cycles - 1) // 2
        # (this equality is only valid because length_cycles is even)
        self.channel_synchronizer.add({
            "function": DMASynchronizer.ARBITRARY_CONTINUED, 
            "self": self, 
            "args": (), 
            "kwargs": {
                "channel": channel, 
                "length": (length_cycles - 1) // 2},
            "retval": None})

        logger.debug(f"Scheduled stretched waveform on channel"
                     f" {channel} with first arbitrary part lasting"
                     f" {length_cycles // 2} cycles, a stretch length of"
                     f" {stretch_length}, and a second arbitrary part lasting"
                     f" {(length_cycles - 1) // 2} cycles")

    @requires_sequencer
    def schedule_direct(self, 
                        channel: Union[Channel, str], 
                        command_source):
        """
        Schedules a DMA command constructed elsewhere.

        For certain kinds of dynamic sequences, it's desirable to be able to play a pulse
        chosen at runtime. Therefore, we need to be able to fetch a DMA command from a source
        and issue it to the DMA without knowing what its fields contain. That is, we fetch a word
        of data from some source assuming that it was assembled properly into a DMA command, and 
        we write it directly to the DMA FIFO.  
        """
        self.channel_synchronizer.add({
            "function": DMASynchronizer.DIRECT, 
            "self": self, 
            "args": (), 
            "kwargs": {
                "channel": channel, 
                "command": command_source},
            "retval": None})

    @requires_sequencer
    def dwell(self,
                channel: Union[Channel, str, None] = None,
                length: Union[float, Symbol, Operation] = None,
                length_is_minus_one: bool = False) -> None:
        """
        Schedule a dwell on a channel's DMA.

        :param channel: Channel to stream
        :type channel: :class:`Channel`
        :param length: The length of the dwell.
            When a `float` is provided, this is the number of seconds for the dwell.
            When a sequencer source is provided, no conversion is performed; it is 
            assumed that the source contains the length in units of cycles.
        :type length: float, Register, DSP
        :param length_is_minus_one: If ``True``, the provided length is understood 
            to be one less than the actual length to be included in the command. 
        :type length_is_minus_one: bool
        """

        if np.issubdtype(type(length), float):
            length = self.seconds_to_cycles(length)
        elif isinstance(length, self.sequencer().Register):
            # Do nothing, registers can be passed directly into the synchronizer
            logger.debug(f"Scheduling dwell on channel {channel} from {length}")
        elif isinstance(length, self.sequencer().DSP):
            # Need to be more cautious, but is acceptable
            logger.warning(f"Scheduling dwell on channel {channel} from {length};"
                            f" ensure that the DSP is not automatically updating,"
                            f" as this can lead undefined behavior when the DSP"
                            f" value is reused during alignment.")
        elif isinstance(length, Symbol):
            if np.issubdtype(length.value_type(), float):
                length = Operation(Acadia.seconds_to_cycles, self, length)
            elif np.issubdtype(length.value_type(), int) or length.value_type() in [np.uint32, np.int32]:
                pass # We can just leave this as-is
            else:
                raise TypeError(f"Symbolic length must use either"
                                f" int or float for a value type;"
                                f" found {length.value_type()}")
        elif isinstance(length, Operation):
            logger.debug(f"Found length derived from an Operation;"
                        f" assuming that the result is in units of cycles.")
            # No further action required
        else:
            raise TypeError(f"Invalid type for length: {type(length)}")

        self.channel_synchronizer.add({
            "function": DMASynchronizer.DWELL, 
            "self": self, 
            "args": (), 
            "kwargs": {
                "channel": self.channel(channel), 
                "length": length,
                "length_is_minus_one": length_is_minus_one},
            "retval": None})

    @requires_sequencer
    def stream_direct(self, 
                      src: Union[Channel, StreamConfiguration, WaveformMemory],
                      dst: WaveformMemory, 
                      length: float = None,
                      output_offset_bytes: Union[int, Source, None] = None) -> tuple[StreamConfiguration, WaveformMemory]:
        """
        Stream data from an input of the stream processing path directly into memory. 
        
        The amount of data streamed into memory is controlled by the 
        ``length`` parameter. If provided, this must be a float representing
        the number of seconds for which to accept data. If not provided, the
        amount of time is chosen so as to fill the destination.
        """
        
        if isinstance(src, StreamConfiguration):
            if src.module != "memory":
                raise TypeError(f"The StreamConfiguration provided to"
                                f" stream_direct must represent a"
                                f" direct-to-memory module (received"
                                f" configuration for module type {src.module})")
            configuration = src
        elif isinstance(src, (Channel, str)):
            configuration = self._request_stream_configuration(self.channel(src), "memory")
        elif isinstance(src, WaveformMemory) or isinstance(type(src), ManagedResource):
            configuration = self._request_stream_configuration("memory", "memory")
        else:
            raise TypeError(f"Unable to create stream with source {src}")

        if length is None:
            length_cycles = 8 * dst.nbytes // self._firmware["stream_processing_path"]["width"]
        elif np.issubdtype(type(length), float):
            length_cycles = self.seconds_to_cycles(length)
        else:
            raise TypeError(f"Invalid type for direct stream length: {type(length)}")

        if dst.itemsize != 2:
            raise TypeError(f"Destinations for direct streams must have 16-bit quadratures;"
                            f" found dtype {dst.dtype}")

        # Because this is a direct stream, we can infer the output size from the length of the stream
        output_size_bytes = length_cycles * self._firmware["stream_processing_path"]["width"] // 8

        logger.debug(f"Direct stream of length {length_cycles} cycles"
                     f" and {output_size_bytes} bytes.")

        self.stream(configuration, 
                    dst, 
                    (src if isinstance(src, WaveformMemory) else None),
                    length_cycles,
                    output_size_bytes,
                    output_offset_bytes)

    @requires_sequencer
    def stream_cmacc(self, 
                     src: Union[Channel, str, StreamConfiguration, WaveformMemory],
                     dst: WaveformMemory, 
                     length: float = None,
                     output_offset_bytes: Union[int, Source, None] = None,
                     kernel: Union[np.ndarray, WaveformMemory, float, None] = None,
                     preload: Union[tuple[int], None] = (0,0),
                     write_mode: Literal["upper", "lower", "input", "none", None] = "upper", 
                     last_only: bool = True, 
                     reset_fifo: bool = False,
                     accumulator_done: bool = False) -> tuple[StreamConfiguration, WaveformMemory]:
        """
        Stream data from an input of the stream processing path, through
        a CMACC, and into memory. 

        The complex multiplier-accumulator (CMACC) accepts a stream of data,
        multiplies each incoming sample by the corresponding value of a 
        "kernel", and progressively sums all of the products ("accumulates") 
        into a register (the "accumulator"). An output port on the CMACC can
        be configured to write the value of the accumulator or a copy of the 
        input stream into memory, and one can configure whether the entire stream
        is written or exclusively the last value. The amount of data processed 
        by the CMACC, its method of processing, and the amount of data written 
        into memory are all independently variable and are described below.
        
        The amount of data accepted into the CMACC is controlled by the 
        ``length`` parameter. If provided, this must be a float representing
        the number of seconds for which to accept data. If not provided, the
        amount of time is chosen to match that of the accumulation kernel.
        
        The accumulation kernel to be used is controlled by the ``kernel`` parameter.  
        
        - If this is a numpy array, its shape information 
            is used in order to determine the size of the kernel. A new kernel 
            memory object is allocated and returned. 
            
        - If this is a WaveformMemory whose region is the kernel memory for the source Channel, 
            no new kernel will be allocated, and the CMACC will be configured to use 
            this previously-allocated kernel.
            
        - If this is a WaveformMemory whose region is not the kernel memory 
            for the source Channel, a new kernel will be allocated with a
            matching number of samples. 
            
        - If this is a float, this should be the length in seconds of a new kernel 
            to be allocated. 
            
        - If ``None``, a single-element kernel is newly allocated to allow for 
            boxcar accumulation. In this case, note that ``length`` must be provided.

        The ``write_mode`` parameter controls which data is presented at the
        output port of the CMACC, with the following options:

        - "upper": The upper 32 bits of each quadrature in the accumulator are presented to the
            output, and the lower 16 bits of each quadrature are discarded.

        - "lower": The lower 32 bits of each quadrature in the accumulator are written to the
            output, and the upper 16 bits of the accumulator value are discarded.

        - "input": The input data is duplicated at the output (after the initial
            factor-of-4 decimation). The accumulator still runs and its value is
            accessible via the bus interface.

        - "none" or ``None``: No data is written to the output. The accumulator 
            still runs and its value is accessible via the bus interface.

        The CMACC can be configured to present data every single cycle by setting ``last_only=False``.
        In this situation, a stream of data equal in length (of time) to the input stream
        is written to the output. For ``write_mode="upper"`` or ``"lower"``, the
        output stream will consist of partial sums of the accumulated input stream.
        That is, each sample in the output stream is the sum of all the samples before
        it, plus the new sample accumulated in that cycle. This allows one to capture
        the value of the accumulator throughout its operation. For ``write_mode="input"``,
        the stream written to the output port will consist of the input stream that is
        being accumulated by the CMACC. This is particularly useful for debugging and for
        calibrating the accumulation kernel, as this is a direct view of the data that would
        be multiplied against the kernel and accumulated.

        Alternatively, the CMACC can be configured to write only the last value of its output
        stream to the output port by setting ``last_only=True``. This is primarily intended 
        for situations in which only the fully accumulated input is necessary; in this case,
        the value of the accumulator during its operation is of no relevance, and only the
        final value should be written. When ``last_only=True``, only a single value will be
        written to the output port regardless of the amount of data accepted into the CMACC.

        When beginning a capture, the hardware does not adjust the value stored in the 
        accumulator. This means that incoming samples will be accumulated on top of whatever
        value was already there; however, by providing a value for ``preload``, a known value will
        be loaded into the CMACC before beginning the capture. The format for ``preload`` is a tuple
        of two ``int``s, corresponding to the values to be loaded into the real and imaginary parts of
        the accumulator. 
        """

        if length is None and (kernel is None or (hasattr(kernel, "size") and kernel.size == 1)):
            raise ValueError(f"Must provide length when kernel is not"
                                " provided or a boxcar kernel is used.")

        # 32-bit quadratures are required for CMACC output
        if dst.itemsize != 4:
            raise TypeError(f"CMACC streams require destinations with"
                            f" 32-bit quadratures; destination has dtype"
                            f" {dst.dtype}")

        configuration, kernel_memory = self.configure_cmacc(
            src, kernel, write_mode, last_only, reset_fifo, accumulator_done)

        if preload is not None:
            self.cmacc_load(configuration, preload)

        if length is None:
            # infer the length in time from the kernel (one cycle per kernel sample)
            # we already checked whether we have a boxcar kernel, so we're good to just
            # look at the kernel size
            length_cycles = kernel_memory.size
            logger.debug(f"Inferring CMACC stream length from kernel memory ({length_cycles} cycles)")
        elif np.issubdtype(type(length), float):
            length_cycles = self.seconds_to_cycles(length)
            logger.debug(f"Converted float to CMACC stream length ({length_cycles} cycles)")
        else:
            raise TypeError(f"Received invalid type for CMACC stream length: {type(length)}")

        # If we're not writing only the last sample, 
        # then we're writing one sample every cycle
        if last_only:
            output_size_samples = 1
        else:
            output_size_samples = length_cycles

        output_size_bytes = output_size_samples * (2*dst.itemsize)
        
        self.stream(configuration=configuration, 
                    dst=dst,
                    length_cycles=length_cycles,
                    output_size_bytes=output_size_bytes,
                    offset_bytes=output_offset_bytes,
                    memory_input=(src if configuration.input_source == "memory" else None))

        return configuration, kernel_memory
        
    @requires_sequencer
    def stream(self, 
               configuration: StreamConfiguration, 
               dst: WaveformMemory, 
               memory_input = None,
               length_cycles: Union[int, None] = None,
               output_size_bytes: Union[int, None] = None,
               offset_bytes: Union[int, Source] = None) -> None:
        """
        Stream data from a source to a destination WaveformMemory. 

        This function initiates a stream from some source into the input of the 
        stream processing path and commands the DataMover of the receiving module. 
        Before calling this function, the module receiving and processing the stream 
        must have been prepared (by calling a function such as :meth:`configure_dsp` or 
        :meth:`configure_cmacc`). 

        For all configurations, an offset may be provided and will be interpreted as the 
        number of bytes into the destination at which to start storing data. 
        This may either be an int or a sequencer source. It is up to 
        the user to ensure that when providing an offset, the length of the stream (either
        provided or inferred) is chosen so that data is not written past the end of the
        destination memory space.

        :param dst: Data destination
        :type dst: :class:`WaveformMemory`
        :param length: Length of data to stream in samples. Note that this
            is the length after any decimation.
        :param offset: Offset within `dst` at which the stream will be written,
            in units of samples. Note that this offset is applied after any 
            decimation.
        :param configuration: Stream configuration to use. If `None`, a new one
            will be requested.
        :type configuration: :class:`StreamConfiguration`
        :return: The configuration used for streaming
        :rtype: :class:`StreamConfiguration`
        """

        # Validate parameters
        if not isinstance(configuration, StreamConfiguration):
            raise TypeError(f"Received invalid type for stream configuration"
                            f" (received type {type(configuration)})")

        if isinstance(configuration.input_source, Channel):
            if memory_input is not None:
                raise TypeError(f"Cannot provide a memory input when using stream"
                                " configurations with Channel inputs")

        logger.debug(f"Creating stream with configuration {configuration}")

        if not isinstance(dst, WaveformMemory):
            raise TypeError(f"Stream destination must be a WaveformMemory;"
                            f" received {type(dst)}")

        logger.debug(f"Stream destination at address {dst.byte_address:010X}")

        if np.issubdtype(type(length_cycles), int) or isinstance(length_cycles, (np.uint32, np.int32)):
            if length_cycles <= 0:
                raise ValueError(f"Received invalid length_cycles: {length_cycles}")
            logger.debug(f"Using stream length {length_cycles} cycles")
        elif isinstance(length_cycles, self.sequencer().Register):
            logger.debug(f"Using indeterminate stream length from {length_cycles}")
        elif isinstance(length_cycles, self.sequencer().DSP):
            logger.warning(f"Scheduling stream from {length};"
                            f" ensure that the DSP is not automatically updating,"
                            f" as this can lead undefined behavior when the DSP"
                            f" value is reused during alignment.")
        else:
            raise TypeError(f"Received object of invalid type for length_cycles:"
                            f" {type(length_cycles)}")

        if output_size_bytes is None:
            if offset_bytes is not None:
                raise ValueError(f"Use of an offset is not allowed when matching"
                                f" stream size to destination size."
                                f" (found offset {offset_bytes}).")

            output_size_bytes = dst.nbytes
            logger.debug(f"Inferring stream output size from destination ({output_size_bytes} bytes)")
        elif np.issubdtype(type(output_size_bytes), int) or isinstance(output_size_bytes, (np.uint32, np.int32)):
            if output_size_bytes <= 0:
                raise ValueError(f"Received invalid output size: {output_size_bytes}")

            if output_size_bytes == dst.nbytes and offset_bytes is not None:
                # Is this redundant?
                raise ValueError("Detected an output size chosen to fill a destination memory"
                                "with a non-None offset. ")
                        
            if output_size_bytes > dst.nbytes:
                raise ValueError(f"Stream output size ({output_size_bytes} bytes)"
                                f" exceeds destination size ({dst.nbytes} bytes)")

            logger.debug(f"Using provided stream output size of {output_size_bytes} bytes")
        else:
            raise ValueError(f"Received object of invalid type for"
                            f" output_size_bytes: {type(output_size_bytes)}")

        if offset_bytes is None:
            offset_bytes = 0
        elif np.issubdtype(type(offset_bytes), int) or isinstance(offset_bytes, (np.uint32, np.int32)):
            if offset_bytes < 0:
                raise ValueError(f"Received invalid offset: {offset_bytes}")
            logger.debug(f"Using output offset of {offset_bytes} bytes")
        elif isinstance(offset_bytes, self.sequencer().Register):
            logger.debug(f"Using indeterminate stream offset {offset_bytes}")

        self._command_datamover(configuration.output_datamover(), 
                                dst.byte_address + offset_bytes,
                                output_size_bytes)

        if isinstance(configuration.input_source, Channel):
            # notify the synchronizer, which will then add the DMA command for us   
            self.channel_synchronizer.add({
                "function": DMASynchronizer.CONSTANT_CONTINUED, 
                "self": self, 
                "args": (), 
                "kwargs": {"channel": configuration.input_source, "length": length_cycles},
                "retval": None})
        else:
            self._command_datamover(f"input{configuration.input_switch_master}_datamover", 
                                   memory_input.byte_address,
                                   memory_input.nbytes)
    
    @requires_sequencer
    def configure_dsp(self, 
                    src: Union[Channel, WaveformMemory], 
                    decimation: int = 1,
                    reset: bool = True,
                    configuration: StreamConfiguration = None) -> StreamConfiguration:
        """
        Configure a DSP for streaming data. 
        
        The source of data can either be a :class:`Channel` representing an 
        ADC, or it can be an array in memory captured by an :class:`Array`
        object. The ``decimation`` property of ``dst`` will be used to 
        determine whether the stream passed directly from the input into memory
        or whether a DSP module will be used for decimating the stream.

        :param src: Data source. If a configuration is provided and this is of
            type :class:`Channel`, the channel in the configuration must match.
        :type src: :class:`Channel` or :class:`Array`
        :param decimation: The decimation to use for the DSP. This must either 
            be 1 or a multiple of 4.
        :type decimation: int
        :param configuration: Stream configuration to use. If `None`, a new one
            will be requested.
        :type configuration: :class:`StreamConfiguration`
        :return: The configuration used for streaming
        :rtype: :class:`StreamConfiguration`
        """

        config_src = src if isinstance(src, Channel) else "memory"
        module = "memory" if decimation == 1 else "dsp"
        if configuration is None:
            configuration = self._request_stream_configuration(config_src, module)

        if decimation != 1:
            # Configure the DSP for decimation
            # At packet start and counter start, we'll load in the input value
            # Otherwise, when we receive valid data, we'll add it to P
            dsp_address = self._firmware.sequencer_bus_decoder[f"module{configuration.input_switch_slave}_registers"].address().value()
            logger.debug(f"Configuring DSP module {configuration.input_switch_slave} at bus address 0x{dsp_address:08X}")

            if reset:
                self.sequencer().bus_write(address=dsp_address, data=(1 << 4))
                self.sequencer().nop()
                self.sequencer().nop()
            
            # P = multiplier: CIN = 0, W = 00, Z = 000, Y = 01, X = 01, ALUMODE = 0000 (W+X+Y+Z+CIN)
            self.sequencer().bus_write(address=dsp_address + 9, data=int("00000001010000", 2)) # packet start config
            self.sequencer().bus_write(address=dsp_address + 10, data=int("00000001010000", 2)) # counter start config
            
            # P = multiplier + P: CIN = 0, W = 01, Z = 000, Y = 01, X = 01, ALUMODE = 0000 (W+X+Y+Z+CIN)
            self.sequencer().bus_write(address=dsp_address + 11, data=int("00100001010000", 2)) # counter run config
            
            # The DSP module output is bits 46 to 15 of P, so we'll multiply by 
            # 2^15 for both quadratures
            self.sequencer().bus_write(address=dsp_address + 1, data=(1 << 15))
            self.sequencer().bus_write(address=dsp_address + 5, data=(1 << 15))
            
            # No pre-add to the input stream
            self.sequencer().bus_write(address=dsp_address + 2, data=0)
            self.sequencer().bus_write(address=dsp_address + 6, data=0)
            
            # load packet start config
            self.sequencer().bus_write(address=dsp_address, data=(1 << 5)) 
            
            # Counter period low and high
            input_samples_per_cycle = self._firmware["stream_processing_path"]["width"] // 32
            counter_value = (decimation // input_samples_per_cycle) - 1
            logger.debug(f"Assigning counter value {counter_value} ({input_samples_per_cycle} input samples per cycle, decimation {decimation})")

            self.sequencer().bus_write(address=dsp_address + 12, data=(counter_value & 0xFFFF) << 16) # low
            self.sequencer().bus_write(address=dsp_address + 13, data=(counter_value >> 16) & 0xFFFFFFFF) # high
        
        return configuration
        

    @requires_sequencer
    def configure_cmacc(self, 
                        src: Union[Channel, str, StreamConfiguration, WaveformMemory],
                        kernel: Union[np.ndarray, float, None] = None,
                        write_mode: Literal["upper", "lower", "input", "none", None] = "upper", 
                        last_only: bool = True, 
                        reset_fifo: bool = False,
                        accumulator_done: bool = False) -> tuple[StreamConfiguration, WaveformMemory]:
        """
        Configure the CMACC.

        :param src: The source of data to be accumulated by the CMACC
        :type src: Channel or WaveformMemory
        :param kernel: The accumulation kernel, or an object that specified its
            size. If this is a numpy array, its values are ignored, and only its 
            shape information is used in order to determine the size of the 
            kernel allocated in kernel memory. If this is a float, this should be
            the length in seconds of the kernel. If None, a single-element kernel
            is allocated to allow for boxcar accumulation.
        :type kernel: np.ndarray, float, None
        """
        
        if isinstance(src, StreamConfiguration):
            if src.module != "cmacc":
                raise TypeError(f"The StreamConfiguration provided to"
                                f" configure_cmacc must represent a"
                                f" CMACC module (received configuration for module"
                                f" type {src.module})")
            configuration = src
        elif isinstance(src, (Channel, str)):
            configuration = self._request_stream_configuration(self.channel(src), "cmacc")
        elif isinstance(src, WaveformMemory) or isinstance(type(src), ManagedResource):
            configuration = self._request_stream_configuration("memory", "cmacc")
        else:
            raise TypeError(f"Unable to create stream configuration with source {src}")
        
        kernel_type = self.CMACCKernelArray[configuration.module_resource._resource_id]
        
        # Determine whether we need to allocate a new kernel or not
        if isinstance(kernel, WaveformMemory) and isinstance(kernel._resource, kernel_type):
            # We already have a kernel and we're good to go, don't allocate a new one
            kernel_length_elements = kernel.size
            logger.debug(f"Using already-allocated kernel WaveformMemory of length {kernel_length_elements} samples")

        else:
            # We don't already have a kernel, so we need to allocate one
            # Figure out how much memory to allocate for the kernel
            if kernel is None:
                # Boxcar kernel
                kernel_length_elements = 1
            elif np.issubdtype(type(kernel), float):
                # Use a length in seconds given by kernel
                kernel_length_elements = self.seconds_to_cycles(kernel)
            elif isinstance(kernel, (np.ndarray, WaveformMemory)):
                # Allocate enough space to store the numpy array (after converting to samples)
                kernel_length_elements = kernel.size
            else:
                raise TypeError(f"Invalid type for specifying CMACC kernel (received {type(kernel)})")
        
            logger.debug(f"Allocating kernel WaveformMemory of length"
                        f" {kernel_length_elements} samples")

            kernel = WaveformMemory(shape=kernel_length_elements, 
                                    dtype="<i2", 
                                    resource_allocator=kernel_type)

        registers = self._firmware.sequencer_bus_decoder[f"module{configuration.input_switch_slave}_registers"].address().value()

        # resource id is the byte offset of the memory segment within its region 
        kernel_index = kernel._resource._resource_id // (2*kernel.itemsize) 

        # Set the kernel start and end addresses
        # The kernel uses one 32-bit element per cycle
        kernel_reg = kernel_index | ((kernel_index + kernel_length_elements - 1) << 16)
        kernel_reg &= 0xFFFFFFFF
        self.sequencer().bus_write(address=registers+3, data=kernel_reg)
            
        control_reg = 0

        # Load the kernel pointer from its buffer register
        control_reg |= 1 << 0
        
        if accumulator_done:
            control_reg |= 1 << 18
            
        if write_mode == "upper":
            control_reg |= 1 << 21
        elif write_mode == "lower":
            control_reg |= 2 << 21
        elif write_mode == "input":
            control_reg |= 3 << 21
        elif write_mode is None or write_mode == "none":
            pass
        else:
            raise ValueError(f"Unexpected value for write_mode: {write_mode}")
        
        if last_only:
            control_reg |= 1 << 23
            
        if reset_fifo:
            control_reg |= 1 << 24
            
        logger.debug(f"Configured CMACC for kernel at address 0x{kernel_index:04X}"
                     f" of length {kernel_length_elements} and set control register to"
                     f" 0x{control_reg:08X}")
        self.sequencer().bus_write(address=registers+2, data=control_reg)

        return configuration, kernel
        
    
    @requires_sequencer
    def cmacc_done(self, configuration: StreamConfiguration):
        """
        Create a condition to check whether the CMACC accumulation for a given
        stream configuration is done.

        :param configuration: Configuration whose CMACC should be checked
        :type configuration: :class:`StreamConfiguration`
        :return: A condition for checking whether the CMACC for the given
            configuration has completed its accumulation
        """
        if not isinstance(configuration.module_resource, 
                          self._stream_module_resources["cmacc"]):
            raise TypeError(f"CMACC completion can only be checked for stream" 
                            f" configurations that drive CMACC modules"
                            f" (found module resource type"
                            f" {type(configuration.module_resource)})")
            
        module_name = f"module{configuration.input_switch_slave}_registers"
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        
        return self.sequencer().bus_read(registers+2, 
                                         latency=self._bus_latency(module_name)) & (1 << 18)
        
    @requires_sequencer
    def cmacc_get_quadrant(self, 
                           configuration: StreamConfiguration, 
                           wait_for_completion: bool = True):
        """
        Get the quadrant of the CMACC value. By default, we'll wait for the 
        CMACC value to be available and then return the quadrant information
        in a way which optimizes latency (because the bus address for 
        checking completion is the same for checking quadrant, we don't need
        to incur the bus latency overhead a second time). Otherwise, a regular
        bus read will be performed with all typical latency overheads.
        
        A different constant is returned depending on the quadrant; refer to
        the constants Acadia.CMACC_QUADRANT_1/2/3/4 for their values.
        """
        
        if wait_for_completion:
            with self.sequencer().repeat_until(self.cmacc_done(configuration)):
                pass
            
        module_name = f"module{configuration.input_switch_slave}_registers"    
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        latency = 0 if wait_for_completion else self._bus_latency(module_name)
        value = self.sequencer().bus_read(registers+2, latency=latency)
        return value & ((1 << 20) | (1 << 19))
    
    @requires_sequencer
    def cmacc_get_quadrature(self, 
                           configuration: StreamConfiguration, 
                           wait_for_completion: bool = True,
                           imag=False):
        """
        Get a quadrature of the CMACC value. By default, we'll wait for the 
        CMACC value to be available and then return the quadrant information
        in a way which optimizes latency (because the bus address for 
        checking completion is the same for checking quadrant, we don't need
        to incur the bus latency overhead a second time). Otherwise, a regular
        bus read will be performed with all typical latency overheads.
        """
        
        if wait_for_completion:
            with self.sequencer().repeat_until(self.cmacc_done(configuration)):
                pass
            
        module_name = f"module{configuration.input_switch_slave}_registers"    
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        latency = 0 if wait_for_completion else self._bus_latency(module_name)
        return self.sequencer().bus_read(registers+imag, latency=latency)
    
    @requires_sequencer
    def cmacc_load(self, 
                    configuration: StreamConfiguration, 
                    value: tuple[int] = (0,0)):
        """
        Load a value into the accumulator of the given CMACC.
        """
        if configuration.module != "cmacc":
            raise TypeError(f"The StreamConfiguration provided to"
                            f" load_cmacc must represent a"
                            f" CMACC module (received configuration for module"
                            f" type {configuration.module})")
        
        module_name = f"module{configuration.input_switch_slave}_registers"    
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        self.sequencer().bus_write(address=registers, data=value[0])
        self.sequencer().bus_write(address=registers+1, data=value[1])

        
    @DMASynchronizer.synchronized(DMASynchronizer.BARRIER, "channel_synchronizer")
    def barrier(self):
        """
        Insert a synchronization barrier. When a barrier is inserted in a 
        synchronization block, the maximum length of all actions before the
        barrier defines the time at which the barrier is inserted. Delays are
        then inserted for every channel that has an action after the barrier
        so that they start at the time of the barrier.
        """
        # Nothing actually needs to be done here, this just notifies the synchronizer
        pass

    # -------------- CONVENIENCE FUNCTIONS FOR THE SEQUENCER ----------- #

    @requires_sequencer
    def reset_all_streams(self):
        for idx,module_dict in enumerate(self._firmware["stream_processing_path"]["modules"]):
            address = self._firmware.sequencer_bus_decoder[f"module{idx}_s2mm_datamover_controller"].address().value()
            self.sequencer().bus_write(address=address+2, data=0x80000000)
            
            # Reset the module
            if module_dict["kind"] == "adder":
                address = self._firmware.sequencer_bus_decoder[f"module{idx}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 2))
            elif module_dict["kind"] == "dsp":
                address = self._firmware.sequencer_bus_decoder[f"module{idx}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 4))
            elif module_dict["kind"] == "cmacc":
                address = self._firmware.sequencer_bus_decoder[f"module{idx}_registers"].address().value() + 2
                self.sequencer().bus_write(address=address, data=(1 << 24))

        for i in range(20):
            self.sequencer().nop()
        
    @requires_sequencer
    def stream_reset(self, configuration: StreamConfiguration = None):
        """
        Reset the datamover controller, module, and any associated FIFOs.
        """
        # Reset the DataMover controller
        if configuration is None: 
            configurations = self._stream_configurations
        else:
            configurations = [configuration]
            
        for cfg in configurations:
            address = self._firmware.sequencer_bus_decoder[f"{cfg.output_datamover()}_controller"].address().value()
            self.sequencer().bus_write(address=address+2, data=0x80000000)
            
            # Reset the module
            if cfg.module_resource.kind == "adder":
                address = self._firmware.sequencer_bus_decoder[f"module{cfg.input_switch_slave}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 2))
            elif cfg.module_resource.kind == "dsp":
                address = self._firmware.sequencer_bus_decoder[f"module{cfg.input_switch_slave}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 4))
            elif cfg.module_resource.kind == "cmacc":
                address = self._firmware.sequencer_bus_decoder[f"module{cfg.input_switch_slave}_registers"].address().value() + 2
                self.sequencer().bus_write(address=address, data=(1 << 24))

    @requires_sequencer
    def stream_count(self, configuration: StreamConfiguration):
        """
        Retrieve the number of status words produced for the DataMover in the 
        provided stream configuration.

        :param configuration: Configuration to check
        :type configuration: :class:`StreamConfiguration`
        """
        datamover_name = configuration.output_datamover() + "_controller"
        address = self._firmware.sequencer_bus_decoder[datamover_name].address().value() + 1
        return self._active_sequencer.bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status count for {datamover_name}",
                                        latency=self._bus_latency(datamover_name))
    
    @requires_sequencer
    def stream_total_bytes_transferred(self, configuration: StreamConfiguration):
        """
        Retrieve the number of status words produced for the DataMover in the 
        provided stream configuration.

        :param configuration: Configuration to check
        :type configuration: :class:`StreamConfiguration`
        """
        datamover_name = configuration.output_datamover() + "_controller"
        address = self._firmware.sequencer_bus_decoder[datamover_name].address().value() + 2
        return self.sequencer().bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status count for {datamover_name}",
                                        latency=self._bus_latency(datamover_name))  
    
    @requires_sequencer
    def stream_set_offset(self, configuration: StreamConfiguration, offset):
        """
        Apply an offset for a DataMover controller.
        """
        datamover_name = f"{configuration.output_datamover()}_controller"
        bus_address_base = self._firmware.sequencer_bus_decoder[datamover_name].address().value()
        self._active_sequencer.bus_write(address=bus_address_base+3, 
                                         data=offset,
                                         comment=f"Set offset for"
                                                 f" {datamover_name}")
                    
    @requires_sequencer
    def channel_trigger(self, *channels):
        """
        Trigger the DMAs associated with the provided channels.

        :param channels: List of channels
        """
        mask = 0
        for channel in channels:
            mask |= 1 << (channel.num() if channel.is_dac else (channel.num() + 16))

        dma_trigger_device = self._firmware.sequencer_bus_decoder["dma_trigger"]
        self.sequencer().bus_write(address=dma_trigger_device.address().value(),
                                 data=mask,
                                 comment="DMA trigger")
        
    @requires_sequencer
    def channel_block(self, *channels):
        """
        Wait until the DMAs for the specified channels are not running.
        """
        mask = 0
        for channel in channels:
            mask |= (channel.num() if channel.is_dac else (channel.num() + 16))

        dma_running_device = self._firmware.sequencer_bus_decoder["dma_running"]
        dma_running = self.sequencer().bus_read(address=dma_running_device.address().value(),
                                                      latency=self._bus_latency("dma_running"))
        with self.sequencer().repeat_until(dma_running & mask == 0):
            pass
        
    @requires_sequencer
    def dma_reset(self, channel: Union[str, Channel]):
        """
        Reset the DMA associated with the provided channel
        """
        channel = self.channel(channel)
        dma_name = f"{'dac' if channel.is_dac else 'adc'}{channel.num()}_dma"
        dma_regs_address = self._firmware.sequencer_bus_decoder[dma_name].address().value() 
        self.sequencer().bus_write(address=dma_regs_address + (1 << 2),
                                 data=0x00000001,
                                 comment=f"Reset DMA {dma_name}")
        
    @requires_sequencer
    def dma_status(self, channel: Union[str, Channel]):
        """
        Retrieve the status information for the DMA associated with the provided channel.
        
        The result is a 32-bit word with the following bit flags:
            Bit 0: running
            Bit 1: FIFO empty
            Bit 2: FIFO full
            Bit 3: FIFO almost empty
            Bit 4: FIFO almost full

        :param channel: Channel to interrogate
        :type channel: :class:`Channel`
        """
        channel = self.channel(channel)
        dma_name = f'{"dac" if channel.is_dac else "adc"}{channel.num()}_dma'
        dma_regs_address = self._firmware.sequencer_bus_decoder[dma_name].address().value()
        bus_op = self.sequencer().bus_read(dma_regs_address, latency=self._bus_latency(dma_name))
        return bus_op

    @requires_sequencer
    def channel_is_fifo_empty(self, channel: Union[str, Channel]):
        """
        Check whether the FIFO for the provided channel's DMA is empty.

        :param channel: Channel to check
        :type channel: :class:`Channel`
        """
        # Mask away the irrelevant_bits
        return self.dma_status(channel) & (1 << 1) != 0

    @requires_sequencer
    def channel_is_fifo_full(self, channel: Union[str, Channel]):
        """
        Check whether the FIFO for the provided channel's DMA is full.

        :param channel: Channel to check
        :type channel: :class:`Channel`
        """
        # Mask away the irrelevant_bits
        return self.dma_status(channel) & (1 << 2) != 0

    @requires_sequencer
    def channel_is_fifo_almost_empty(self, channel: Union[str, Channel]):
        """
        Check whether the FIFO for the provided channel's DMA is almost empty.

        :param channel: Channel to check
        :type channel: :class:`Channel`
        """
        # Mask away the irrelevant_bits
        return self.dma_status(channel) & (1 << 3) != 0

    @requires_sequencer
    def channel_is_fifo_almost_full(self, channel: Union[str, Channel]):
        """
        Check whether the FIFO for the provided channel's DMA is almost full.

        :param channel: Channel to check
        :type channel: :class:`Channel`
        """
        # Mask away the irrelevant_bits
        return self.dma_status(channel) & (1 << 4) != 0
    
    @requires_sequencer
    def channels_running(self, *channels):
        """
        Create a condition that will determine whether the DMAs
        driving the given :class:`Channel`\s are running.

        :param channels: Channel(s) to check
        :type channels: list of :class:`Channel`
        """

        mask = 0
        for channel in channels:
            mask |= (channel.num() if channel.is_dac else (channel.num() + 16))
        
        bus_address = self._firmware.dma_running.address().value()

        return self.sequencer().bus_read(bus_address, 
                                        latency=self._bus_latency("dma_running"))

    # -------------- RUNTIME UTILITIES ----------- #
    
    def run(self, configure_streams: bool = True, block: bool = True, minimum_delay: int = 0):
        """
        Run a sequence on Acadia hardware.
        
        :param configure_streams: If ``True``, the streams of the stream processing
            path will be configured before running the sequencer. 
        :type configure_streams: bool
        :param block: If `True`, execution will block until the sequencer
            signals completion.
        :type block: bool
        :param minimum_delay: The minimum amount of time (in nanoseconds) that must have
            elapsed since the sequencer last completed its execution. If not satisfied,
            this function will block until the minimum delay is met. The exact delay time 
            is only guaranteed to be longer than the specified delay, but is may be longer
            and may differ from call to call. Note that the last
            completion time is noted by :meth:`complete`; if `block=False`, :meth:`complete` 
            must be called manually in order to correctly timestamp the execution completion
            time.
        :type minimum_delay: int
        """

        if configure_streams:
            # Disconnect all of the switch ports so that they can be properly assigned
            # (If we don't disconnect a previous connection, it may not be properly applied
            # since assignment priority is determined by master number, not assignment order;
            # see the description of the MI_MUX registers in the AXI4-Stream Switch IP)
            self._stream_processing_path_input_switch.disconnect()
            self._ADC_input_switch.disconnect()
            for cfg in self._stream_configurations:
                self.configure_stream(cfg)
                
        # Wait for until a required delay, if any
        while(utils.clock_monotonic_ns() - self._previous_run_time < minimum_delay):
            utils.sys_nanosleep(10000)
        
        utils.sequencer_halt_and_reset()
        utils.sequencer_run()
        
        if block:
            self.complete()

    def complete(self):
        """
        Wait for the sequencer to complete its execution.
        """
        utils.sequencer_complete()
        self._previous_run_time = utils.clock_monotonic_ns()

    def configure_stream(self, configuration: StreamConfiguration):
        """
        Configure the stream processing path according to a stream description.
        
        :param stream: Stream configuration to apply
        :type stream: :class:`StreamConfiguration`
        """
        self._stream_processing_path_input_switch.connect(configuration.input_switch_slave, 
                                                          configuration.input_switch_master)
        
        if configuration.adc_switch_master is not None:
            self._ADC_input_switch.connect(configuration.adc_switch_slave, 
                                           configuration.adc_switch_master)
        
    def compile(self, sequence, overwrite=False, output_directory: str = None):
        """
        Compiles the programs for all internally-stored :class:`Processor` 
        objects.
        """
        retval = self.sequence(sequence)
        
        for s in self._sequencer_type.instances:
            s.compile_all(overwrite)

        outfilename = os.path.join(output_directory, "compiled.log") if output_directory is not None else "compiled.log"
        with open(outfilename, "w") as outfile:
            outfile.write(self.sequencer_pprint())    

        return retval

    def assemble(self, output_directory: str = None) -> dict[str,list[int]]:
        """
        Assembles instruction memory for the sequencer and all DMAs. A dictionary
        is produced that contains the memory segments for all required memory and
        a byte offset within the region.
        """

        assembled = {}
            
        # Assemble the sequencer last so that if any DMA descriptors are resolved to have zero length,
        # the instruction driving them will be removed above
        num_sequencer_instructions = sum([len(s._compiled_program) for s in self._sequencer_type.instances])
        logger.debug(f"Assembling sequencer program with {num_sequencer_instructions} instructions")
                
        address = 0
        for s in self._sequencer_type.instances:
            assembled_bin = bytearray(len(s._compiled_program) * 16)
            key = f"seq@{address:08X}"
            for instr in s._compiled_program:
                assembled_bin[address : address+16] = instr.assemble()
                address += 16
            
            assembled[key] = hexlify(assembled_bin).decode("ascii")

        outfilename = os.path.join(output_directory, "assembled.log") if output_directory is not None else "assembled.log"
        with open(outfilename, "w") as outfile:
            json.dump(assembled, outfile, indent=0)
            
        return assembled
    
    def load(self, inp: Union[dict[str,list[int]], str, None] = None) -> None:
        """
        Loads assembled programs into memory. If the input argument is a dict,
        it must have the format as produced by assemble(). If the input is a str,
        an assembled JSON file is loaded from the directory specified by it. 
        If the input is None, the data is loaded from an assembled JSON in the 
        current working directory.
        """

        if inp is None or isinstance(inp, str):
            filename = os.path.join(inp, "assembled.log") if inp is not None else "assembled.log"
            if not os.path.exists(filename):
                raise ValueError(f"Assembled JSON not found at {filename}")
            with open(filename, "r") as file:
                inp = json.load(file)
        elif not isinstance(inp, dict):
            raise TypeError(f"Invalid type of input data {type(inp)}")

        for segment,data in inp.items():
            region_str,offset_str = segment.split("@")
            offset = int(offset_str, base=16)

            if region_str.startswith("seq"):
                buffer = self._sequencer_instruction_memory
                buffer_name = "sequencer instruction"
            else:
                raise ValueError(f"Unrecognized segment {segment}")
            
            assembled_bin = unhexlify(str.encode(data, "ascii"))
            logger.debug(f"Loading {len(assembled_bin)} bytes into {buffer_name} memory at offset {offset}")
            buffer[offset:offset+len(assembled_bin)] = assembled_bin
                        
    def assemble_simulation(self) -> str:
        """
        Identical to :meth:`assemble`, but creates a string for loading memory
        in Verilog testbenches connected to the Zynq Ultrascale AXI VIP.
        """
        sim_string = ""
        for s in self._sequencer_type.instances:
            for idx_instr,instr in enumerate(s._compiled_program):
                assembled = ''.join(reversed([f'{b:02X}' for b in instr.assemble()]))
                address = (s._resource_id + idx_instr)*16
                sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{address + self._firmware['sequencer_instruction_memory']['address']: X}, 16, 128'h{assembled}, resp);\n"
    
        return sim_string

    def sequencer_pprint(self) -> str:
        """
        :return: a "pretty" representation of the programs compiled
            for the sequencer
        :rtype: str
        """
        idx = 0
        output = ""
        for idx_seq,s in enumerate(self._sequencer_type.instances):
            output += f"---- Program {idx_seq} ----\n"
            for instr in s._compiled_program:
                output += f"{idx:04X}: {instr.pprint()}\n"
                idx += 1
            output += "\n"

        return output

    # -------------- SYSTEM UTILITIES ----------- #
            
    def reset_plddr0(self):
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 1)
        utils.sys_nanosleep(1000000)
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 0)

    def reset_plddr1(self):
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 1)
        utils.sys_nanosleep(1000000)
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 0)

    def is_plddr0_cal_complete(self):
        return PSGPIO.sysfs_read(self._ddr4_c0_cal_cplt_gpio)
    
    def is_plddr1_cal_complete(self):
        return PSGPIO.sysfs_read(self._ddr4_c1_cal_cplt_gpio)
        
    def reset_logic(self):
        """
        Resets the PL logic.
        """

        gpio = self._firmware["ps_gpio"]["sysfs_offset"] + 95
        PSGPIO.sysfs_export(gpio)
        PSGPIO.sysfs_set_direction(gpio, "out")
        PSGPIO.sysfs_write(gpio, 0)
        utils.sys_nanosleep(100000000)
        PSGPIO.sysfs_write(gpio, 1)
        
    def gpio_set_direction(self, port, directions):
        """
        Set the GPIO directions for the signals in a given port.

        :param port: The port number (either 3 or 4).
        :type port: int
        :param directions: Each set bit configures the corresponding
            pin as an output.
        :type directions: int
        """

        proc = Processor.active_processor()
        if proc is None:
            self._psgpio_mem[(PSGPIO.PSGPIO3_DIR_PSREG >> 2) + port - 3] = directions
            self._psgpio_mem[(PSGPIO.PSGPIO3_DIR_PSREG >> 2) + port - 3 + 1] = directions
        else:
            raise TypeError(f"Unable to configure GPIO on processor {proc}.")
        
    def gpio_read(self, port):
        """
        Read the value of a 32-bit GPIO port. 

        :param port: The port number (either 3 or 4).
        :type port: int
        """

        if port not in [3,4]:
            raise ValueError(f"Invalid GPIO port {port}.")
        proc = Processor.active_processor()
        if proc is None:
            return self._psgpio_mem[(PSGPIO.PSGPIO3_IN_PSREG >> 2) + port - 3]
        elif isinstance(proc, Sequencer):
            addr = self._firmware.sequencer_bus_decoder[f"ps_gpio{port}"].address().value()
            return proc.bus_read(addr, latency=self._bus_latency(f"ps_gpio{port}"))
        else:
            raise TypeError(f"Unable to access GPIO on processor {proc}.")
        
    def gpio_write(self, port, data):
        """
        Write data to a 32-bit GPIO port. 

        :param port: The port number (either 3 or 4).
        :type port: int
        :param data: The value to write
        :type data: int or bytes
        """

        if port not in [3,4]:
            raise ValueError(f"Invalid GPIO port {port}.")
        proc = Processor.active_processor()
        if proc is None:
            self._psgpio_mem[(PSGPIO.PSGPIO3_OUT_PSREG >> 2) + port - 3] = data
        elif isinstance(proc, Sequencer):
            addr = self._firmware.sequencer_bus_decoder[f"ps_gpio{port}"].address().value()
            return proc.bus_write(address=addr, 
                                  data=data,
                                  comment=f"Write to GPIO port {port}")
        else:
            raise TypeError(f"Unable to access GPIO on processor {proc}.")
        
    
    # -------------- INTERNAL UTILITIES ----------- #
            
    def _create_cache(self):
        def _cache_getitem(cache_self, key):
            proc = Processor.active_processor()
            if proc is None:
                if cache_self.__array_interface__ is None:
                    raise AttributeError(f"Attempted to get item from unattached memory.")
                return cache_self._array[key]
            elif isinstance(proc, Sequencer):
                base_address = self._firmware.sequencer_bus_decoder["cache"].address().value()
                return proc.bus_read(base_address + cache_self.index + key, 
                                     latency=self._bus_latency("cache"))
            return Operation("getitem", cache_self, key)
            
        def _cache_setitem(cache_self, key, value):
            proc = Processor.active_processor()
            if proc is None:
                if cache_self.__array_interface__ is None:
                    raise AttributeError(f"Attempted to set item of unattached memory.")
                cache_self._array[key] = value
            elif isinstance(proc, Sequencer):
                base_address = self._firmware.sequencer_bus_decoder["cache"].address().value()
                proc.bus_write(address=base_address + cache_self.index + key,
                               data=value,
                               comment=f"Write to cache address {key}")
            else:
                raise TypeError(f"Unable to access cache on processor {proc}.")
        
        self.CacheArray = ManagedMemory("CacheArray", 
            (), 
            {"OPERATORS": [], 
             "__getitem__": _cache_getitem, 
             "__setitem__": _cache_setitem},
            base_address=self._firmware["sequencer_cache_memory"]["address"],
            alignment=4,
            memory_size=self._firmware["sequencer_cache_memory"]["size_bits"] // 8,
            getset=None)
        
    def _create_dac_arrays(self):
        self.DACArray = [ManagedMemory(f"DAC{i}Array", 
            (), 
            {"OPERATORS": []},
            base_address=(self._firmware[f"dac_tile{i // 4}_sample_memory"]["address"] 
                               + (i % 4)*(self._firmware[f"dac_tile{i // 4}_sample_memory"]["size_bits"] // 8)),
            alignment=self._firmware["rfdc"]["dac"]["channel_interface_width"][i] // 8,
            memory_size=self._firmware[f"dac_tile{i // 4}_sample_memory"]["size_bits"] // 8,
            getset=None) for i in range(self._firmware.NUM_DACS)]
        
    def _create_cmacc_kernel_arrays(self):
        self.CMACCKernelArray = [ManagedMemory(f"CMACC{i}KernelArray", 
            (), 
            {"OPERATORS": []},
            base_address=(self._firmware["stream_processing_path"]["cmacc_kernel_memory_controller"]["base_address"] 
                               + i*(self._firmware._max_cmacc_memory * 32 // 8)),
            alignment=4,
            memory_size=self._firmware._max_cmacc_memory * 32 // 8) for i in range(self._firmware._num_cmaccs)]
        
    def _create_pl_ddr_arrays(self):            
        self.PLDDR0Array = ManagedMemory(f"PLDDR0Array", 
            (),
            {"OPERATORS": []},
            base_address=self._firmware["memory"]["ddr4_c0"]["address"],
            memory_size=self._firmware["memory"]["ddr4_c0"]["size_bits"] // 8)
        
        self.PLDDR1Array = ManagedMemory(f"PLDDR1Array", 
            (), 
            {"OPERATORS": []},
            base_address=self._firmware["memory"]["ddr4_c1"]["address"],
            memory_size=self._firmware["memory"]["ddr4_c1"]["size_bits"] // 8)
        
    def _create_ps_ddr_arrays(self):
        self.PSDDRArray = ManagedMemory(f"PSDDRArray", 
            (),
            {"OPERATORS": []},
            base_address=0x8_0000_0000,
            memory_size=2**30)
        
    def _create_ocm_arrays(self):
        self.OCMArray = ManagedMemory(f"OCMArray", 
            (), 
            {"OPERATORS": []},
            base_address=0xFFFC_0000,
            memory_size=2**18)
        
    def _create_zdma(self):
        def zdma_postinit(zdma_self):
            zdma_self.fci_bus_address = self._firmware.sequencer_bus_decoder["zdma_controller"].address().value()
            zdma_self.channel = zdma_self._resource_id
            super(zdma_self).__post_init__()
        
        self._ZDMA = ManagedResource("ZDMAResource", 
                                         (ZDMA,), 
                                         {"__post_init__": zdma_postinit,
                                          "OPERATORS": []},
                                         allocation_limit=8)
        
    def _create_channels(self):
        # Create channel objects that abstract the channels of this board
        # so that when parameters are updated, everything that depends on
        # the channel receives the update
        self._DAC_channels = []
        self._ADC_channels = []
        for tile in range(4):
            for block in range(4):
                # By default, the sample rate will be configured to be zero. when we attach it will be read
                dac_channel = Channel(tile=tile, block=block, is_dac=True, 
                    interface_sample_frequency = (self._firmware["clk104_pl_clk"]["freq_hz"]
                                                          * self._firmware["rfdc"]["dac"]["channel_interface_width"][tile*4 + block] // 32),
                    interface_width_bytes = self._firmware["rfdc"]["dac"]["channel_interface_width"][tile*4 + block] // 8)
                self._DAC_channels.append(dac_channel)
                
                adc_channel = Channel(tile=tile, block=block, is_dac=False,
                    interface_sample_frequency = (self._firmware["clk104_pl_clk"]["freq_hz"]
                                                          * self._firmware["rfdc"]["adc"]["channel_interface_width"][tile*4 + block] // 32),
                    interface_width_bytes = self._firmware["rfdc"]["adc"]["channel_interface_width"][tile*4 + block] // 8)
                
                self._ADC_channels.append(adc_channel)
                
    def _create_switches(self):
        self._stream_processing_path_input_switch = AXISSwitch()
        self._ADC_input_switch = AXISSwitch()
        
    def _attach_resource(self, resource_manager: ManagedMemory):
        """
        Maps the memory associated with a managed resource in the physical 
        address space of the hardware. Instances of ``memoryview`` are assigned
        to the resource instances under the attribute ``memory``.
        
        :param resource_manager: Resource with instances to be mapped
        :type resource_manager: :class:`ManagedResource`
        :param mem_cast: The memory type to which the view should be casted,
            as indicated by a ``struct`` format character.
        :type mem_cast: str, optional
        """

        if not isinstance(resource_manager, ManagedMemory):
            raise TypeError(f"Only ManagedMemory objects can be attached; received {resource_manager}")

        logger = logging.getLogger("acadia")
        logger.debug(f"Attaching resource manager {resource_manager} at"
                     f" address 0x{resource_manager._base_address:010X}"
                     f" ({resource_manager._allocation_limit} bytes)")

        m = mmap.mmap(self._mem_file, 
            resource_manager._allocation_limit, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            resource_manager._base_address)
        
        self._mem_maps.append(m)
        resource_manager.attach(m)

        # Also stash some numpy arrays in the instances for easier use later
        for inst in resource_manager.instances:
            array_interface = inst.__array_interface__
            inst._array = np.frombuffer(
                array_interface["data"], 
                dtype=np.dtype(array_interface["typestr"]),
                count=inst.size,
                offset=array_interface["offset"]).reshape(inst.shape)
        
    def _attach_memory(self, address, size, dtype=np.uint8, return_map=False):
        """
        Maps a region of memory in the physical address space of the hardware.
        
        :param address: Physical address to map
        :type address: int
        :param size: Size of the space to map in bytes
        :type size: int
        """

        logging.getLogger("acadia").debug(f"Attaching memory of size {size}"
                                          f" bytes at address 0x{address:010X}"
                                          f" with dtype {dtype}")

        m = mmap.mmap(self._mem_file, 
            size, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            address)
        self._mem_maps.append(m)
        
        if return_map:
            return m
        
        return np.frombuffer(m, dtype=dtype)

    def _command_datamover(self, 
                           datamover_name: str, 
                           address: Union[int, Symbol], 
                           size: Union[int, Symbol], 
                           tag: int = 0xA, 
                           incr: bool = True):
        """
        Configure a DataMover (either MM2S or S2MM).

        :param datamover_name: Name of the DataMover on the sequencer's 
            DataMover controller
        :type datamover_name: str
        :param address: Address for the AXI interface
        :type address: int
        :param size: Transfer size in bytes
        :type size: int
        :param tag: Numeric tag to use in command. Must be between 0 and 15 
            inclusive.
        :type tag: int, optional
        :param incr: If ``True``\, the AXI transaction is in INCR mode.
        :type incr: bool, optional
        :param address_base: If provided, uses the provided value for the upper
            bits of the destination address. This allows the lower 32 bits 
            (provided in ``address``) to be an object on which a bitshift 
            cannot be performed, such as a :class:`Sequencer.Register` or
            :class:`Sequencer.DSP`\.
        :type address_base: int, optional
        """

        if np.issubdtype(type(size), int) or isinstance(size, (np.uint32, np.int32)):
            if size > 2**23:
                raise ValueError(f"Size must be less than 8 MB; received {size}.")
        elif isinstance(size, Symbol) and (np.issubdtype(size.value_type(), int) or size.value_type() in [np.uint32, np.int32]):
            if size.assigned() and size.value() > 2**23:
                raise ValueError(f"Size must be less than 8 MB; received {size}.")
            else:
                logger.warning("Unable to verify size of transfer;"
                                 "ensure that the size is less than 8 MB.") 
        else:
            logger.warning("Unable to verify size of transfer;"
                            "ensure that the size is less than 8 MB.")
                
        transfer_type = int(incr) # INCR transaction
        transfer_eof = 0 # TLAST will arrive with the data
        transfer_tag = tag # Arbitrary value that will be included in the status word
        transfer_cache = 0 # not needed for now
        transfer_user = 0 # not needed for now

        misc_reg = ((transfer_user << 10) 
                    | (transfer_cache << 6) 
                    | (transfer_tag << 2) 
                    | (transfer_eof << 1) 
                    | (transfer_type << 0))
        
        # TODO: is there a way to get from the firmware config that the address bus is 40 bits rather than hardcode it?
        misc_reg |= ((address >> 32) & 0xFF) << 14

        # Configure the DataMover controller (the last bus write will 
        # push the complete command into the command FIFO)
        bus_address_base = self._firmware.sequencer_bus_decoder[f"{datamover_name}_controller"].address().value()
        self._active_sequencer.bus_write(address=bus_address_base+2, 
                                         data=misc_reg,
                                         comment=f"Misc configuration for DataMover"
                                                 f" {datamover_name}")
        self._active_sequencer.bus_write(address=bus_address_base+1, 
                            data=size,
                            comment=f"Transfer size for DataMover {datamover_name}")
        self._active_sequencer.bus_write(address=bus_address_base, 
                            data=(address & 0xFFFFFFFF),
                            comment=f"Base address and dispatch for DataMover {datamover_name}")
               
    def _bus_latency(self, port: str) -> int:
        """
        Get the latency for a port on the sequencer's bus, taking into account
        any pipelining configured in the firmware.

        :param port: Bus port name. Must either be a key in the 
            ``SEQUENCER_BUS``  section of the firmware configuration, or
            ``cache``\.
        :type port: str
        """

        if port not in self._firmware.sequencer_bus_decoder:
            raise ValueError(f"Unrecognized bus port {port}")

        # One cycle to load the bus registers in the sequencer
        latency = 1

        # One cycle if the bus decoder itself has a pipelined MISO
        if self._firmware["sequencer_bus"]["decoder_pipeline_miso"]:
            latency += 1
        
        if "datamover_controller" in port:
            # Datamover controllers have a read latency of 1 because its MISO is driven
            # in a synchronous process, in addition to any bus pipelining
            latency += 1
        elif port == "cache":
            # One additional cycle minimum because the memory has a read latency of 1
            # even before any pipelining because it's a synchronous memory
            latency += 1
            latency += self._firmware["sequencer_cache_memory"]["bus_port_input_pipeline"]
            latency += self._firmware["sequencer_cache_memory"]["bus_port_output_pipeline"]

        # If the bus decoder has a pipeline stage for this device, add a stage
        if self._firmware.sequencer_bus_decoder.is_pipelined(port):
            latency += 1
            
        return latency
    
    def _request_stream_configuration(self, 
                                      input_source: Union[Channel, str], 
                                      module: str) -> StreamConfiguration:
        """
        Request configuration parameters for a stream. Streams are uniquely 
        determined by their input source and by the module that processes them.
        The :class:`Acadia` object will store an internal list of all 
        :class:`StreamConfiguration` objects created with this method and will
        reuse them when an identical configuration is requested.
        
        :param input_source: The source of data driving the stream. If this is 
            a :class:`Channel` object (which must be an ADC), then the default
            behavior will depend on whether the specified ADC is directly 
            connected to the input switch. If a string, it is understood to
            specify the kind of input to request.
        :type input_source: :class:`Channel` or str
        :param module: The kind of stream processing module to use. Must be one
            of "adder", "dsp", or "memory".
        :type module: str
        """
        logger.debug(f"Stream requested for input {input_source} with module type {module}")
        for cfg in self._stream_configurations:
            if cfg.input_source == input_source and cfg.module == module:
                logger.debug(f"Reusing existing configuration {cfg}")
                return cfg
            
        # Establish some hidden fields for mapping requested inputs and 
        # modules to internal switch port numbers
        input_resource = None
        module_resource = None
        adc_switch_master = None
        adc_switch_slave = None
        
        if isinstance(input_source, Channel):
            if input_source.is_dac:
                raise ValueError("Input source channels must be ADCs.")
            
            # We now need to determine which switch input port to use
            # First, check if the ADC is directly connected to the input switch
            name = f"ADC{input_source.num()}"
            if name in self._stream_input_resources:
                input_resource = self._stream_input_resources[name]()
            else:
                input_resource = self._stream_input_resources["ADC_switch"]()                
                adc_switch_slave = input_resource._resource_id
                
                # Figure out which master for the ADC switch it is
                adc_switch_inputs = list(range(self._firmware.NUM_ADCS))
                for inp in self._firmware["stream_processing_path"]["inputs"]:
                    if inp["kind"] == "ADC":
                        adc_switch_inputs.remove(inp["channel"])
                
                # This will raise an exception if it's not in the list
                adc_switch_master = adc_switch_inputs.index(input_source.num())
            
        elif isinstance(input_source, str):
            input_resource = self._stream_input_resources[input_source]()
            
        else:
            raise TypeError(f"Invalid type of input source ({type(input_source)})")
        
        input_switch_master = input_resource.switch_port()
        
        # Now determine which module to use
        if not isinstance(module, str):            
            raise TypeError(f"Invalid type for specifying module: {type(module)}")
        
        module_resource = self._stream_module_resources[module]()
        input_switch_slave = module_resource.switch_port()
        
        cfg = StreamConfiguration(input_source, 
                                   module, 
                                   input_resource, 
                                   module_resource, 
                                   adc_switch_master, 
                                   adc_switch_slave, 
                                   input_switch_master, 
                                   input_switch_slave)

        logger.debug(f"Allocated stream of type {module}, routing incoming data"
                    f" on input switch master {input_switch_master} to"
                    f" slave {input_switch_slave}.")
        if isinstance(input_source, Channel):
            logger.debug(f"ADC switch set to route incoming data on ADC"
                        f" master {adc_switch_master} (ADC {input_source.num()})"
                        f" to switch output {adc_switch_slave}")
        
        self._stream_configurations.append(cfg)
        
        return cfg
        