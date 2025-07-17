# The Acadia Mixed-Signal Instrumentation Platform

William Kalfus, Yale University

# Description

Acadia is a laboratory instrument designed for carrying out complex sequences of signal synthesis and capture. It couples a very simplistic real-time sequencer to a general-purpose high-performance processor and orchestrates them in concert, reaping the benefits of each: the sequencer provides real-time sequencing with conditional control flow with very low latency, while the processor can carry out advanced computation to influence the sequencer's behavior and rapidly generate new sequences. The sequencer's simple nature allows sequence branching to have very low overhead, and because waveform synthesis is always scheduled dynamically by the sequencer, sequences can easily incorporate signal synthesis conditioned on measurements, computation results, memory values, and more. Captured signals pass through a reconfigurable network of processing units that are optimized for different aspects of signal processing such as wide-bandwidth capture, low-latency filtering, and high-precision spectroscopy. A full assembler and compiler are provided that allow complex programs involving the complete system to be expressed simply as Python classes. We also include a runtime manager that seamlessly deploys programs to remote hardware, transparently transfers and archives captured data, and performs arbitrary post-processing and visualization.

Acadia was designed with the challenges of quantum device research in mind, and a more thorough discussion of the associated considerations may be found in [Motivation](docs/motivation.rst). However, its flexibility in orchestrating different signal processing functions allows Acadia to straightforwardly replicate the functionality of common lab instruments like oscilloscopes, signal generators, vector network analyzers, and spectrum analyzers. Along with a high-performance analog front-end, this can drastically lower the cost associated with having these capabilities available in a lab compared to commercial units, and the coexistence of these capabilities can allow bespoke combinations of functionality for unique experiments.

Acadia is targeted for implementation on a ZCU216 development board from Xilinx, though it is straightforwardly portable to other hardware. Many parameters of the design (such as memory depths) can be modified simply by [editing a firmware definition file](pyacadia/acadia/firmware_configurations.py), but the default configuration has shown to be sufficient for many experiments in our lab. Some parameters of the default configuration include:

 - A sequencer with single-cycle instruction decode and execution
   
   - 200 MHz clock rate

   - Two-cycle branch latency

   - 4K-deep instruction memory, able to be reloaded in real-time from external memory

   - Eight 32-bit general-purpose registers

   - Eight 48-bit DSP units for real-time arithmetic

   - 32-bit memory bus for interface to the rest of the system

 - 16 DACs operating at 6.4 GS/s, interpolated from an 800 MS/s fabric interface rate

   - DAC sample rates may be changed dynamically to allow optimal placement of Nyquist zone boundaries

   - 32 KS memory for each DAC channel (just over 40 us at the default rate), indexed by up to 1024 descriptors

   - Waveform memory can be reloaded by the sequencer in real-time from multiple external memory sources

   - A 48-bit numerically-controlled quadrature oscillator capable of modulating the samples at the full DAC bandwidth

 - 16 ADCs operating at 2.4 GS/s, decimated to an 800 MS/s fabric interface rate

   - A 48-bit numerically-controlled quadrature oscillator capable of modulating the samples at the full DAC bandwidth

 - All ADC outputs and two memory-to-stream units feed a stream switch, allowing data streams to be concurrently routed to different processing units

   - Four complex multiplier/accumulator units 
   
     - Real-time signal filtering using an arbitrary integration kernel

     - Provides filtered results to the sequencer within 50 ns

     - Able to be dynamically reset by the sequencer for repeated measurements within a sequence

   - Two full-bandwidth capture paths that write the input stream directly to memory

   - Two programmable DSP units that enable a wide range of operations, including decimation, accumulation, shifting, scaling, and bitwise operations

 - A fast true-dual-port cache memory

   - Organized as 32768 32-bit words
 
   - Optimized for very-low-latency communication between the sequencer and the processor (approximately 100 ns)

   - Direct connections to processor AXI master port and to sequencer bus

 - Two 4 GB banks of external DDR4 RAM

 - A 256-bit AXI interconnect allowing all memory regions to be concurrently accessed by the stream processing units and the processor

# Installation

## Host Computers

Host computers are responsible for deploying procedures onto remote targets, receiving and archiving any data from them, and potentially rendering any live outputs during the procedure.

### OS and Software Requirements

Acadia only supports host computers using an Ubuntu or Debian-based distribution of Linux, either natively or through the Windows Subsystem for Linux (WSL). See [this link](https://learn.microsoft.com/en-us/windows/wsl/install) for information about how to install WSL on Windows machines. This software was developed using Ubuntu 22.04.3 LTS, though any reasonably modern distribution should function properly. Acadia has also been known to function on recent versions of Mac OS, though compatibility is not guaranteed.

The host computer requires a few packages in order to host a proper runtime environment, which may be installed by calling the following at the Linux command line:

```
sudo apt update
sudo apt install python3-pip python3-venv python3-dev gcc expect
```

Though it is not required, we encourage the use of Python virtual environments for managing dependencies. A new Python virtual environment can be created by running 

```
python3 -m venv ~/acadia_env
```

This will create a new environment called `acadia_env` in your home directory (this name and location are arbitrary and no part of Acadia requires the environment to be named this) which you can then enter by calling

```
source ~/acadia_env/bin/activate
```

Your terminal should now indicate that you have entered the `acadia_env` Python environment. You can return to the default Python environment by calling `deactivate`. 

Machines that will be used for deploying procedures onto remote targets 

### Installing/Updating Acadia

Once you have entered your preferred Python environment, download and install the `acadia` package along with all of its requirements by running

```
git clone https://git.yale.edu/RSL/acadia.git
pip3 install acadia/pyacadia
```
### Development Environment

This software supports deployment and runtime management from any Python terminal. However, many users would like to visualize data in real-time, even if just to confirm that deployment is progressing satisfactorily. This is implemented in Acadia through `IPython` and `ipywidgets`, and visualization is supported in any front-end capable of rendering their outputs, such as Jupyter notebooks. 

We primarily encourage the use of this software through VS Code, which may be installed [here](https://code.visualstudio.com/download).

# Hardware setup for ZCU216

## First-time SD card preparation

Please note that the first installation of Acadia must be carried out using a Linux-based machine to which you have sufficient permissions for disk formatting (it is currently unknown whether this can be performed on Windows or through WSL). Some Linux machines are available in RSL; talk to Billy for connection information. You will need a microSD card onto which the boot image will be installed; this will erase all information on the card. This will install the latest firmware, so when this step is carried out you can skip the "Updating firmware" section.

1. Download this repository somewhere onto the PC. 

1. Use a microSD card adapter to plug the card into the PC. 

1. Determine the device path of the card by running `lsblk` at the Linux command line. This will print out one line for each disk and partition in the system, which contains a path like `/dev/sdx` and a device size. Given the device sizes, determine which path corresponds to the SD card. If the disk is already partitioned, there may be a path with a number at the end such as `/dev/sdx1`; ignore this.

1. Use `fdisk` to wipe the card and create a partition for the boot image. We'll create a partition that's only 1GB in size due to bootloader limitations on the FPGA, but you may create additional partitions for data if you like. 

   1. At the command line, run the following:

   ```
   sudo fdisk /dev/sdx # Replace this with the path to your card
   ```

   1. This program will have its own command line. Use `p` to print all the partitions on the card.

   1. Use `d` to delete all the partitions on the card. If there are multiple partitions on the card, continue to delete them until running `d` tells you that there are no partitions defined.

   1. Create a DOS partition table by running `o`. If it tells you that the device contains a signature and will be removed, this is okay and may be ignored.

   1. Create a new partition by running `n`. Use the default values for the partition number and the first sector, but when it asks for the last sector, enter "+1G". If it tells you that the partition contains a signature and asks whether you want to remove it, enter `Y`.

   1. Commit the changes to the disk by running `w`. The program will exit when this is complete.

1. Confirm that the partition was created by running `lsblk`. Now, under the same device path, you should see an entry like `/dev/sdx1` that's listed as being 1GB in size.

1. Format the partition to have a FAT32 filesystem by running `sudo mkfs -t fat /dev/sdx1`.

1. Mount the filesystem on the PC by running `udisksctl mount -b /dev/sdx1`. If this completes successfully, it will tell you the path at which the filesystem was mounted. 

## Installing Pre-built Firmware

1. Obtain the firmware files. This section assumes that you have access to a firmware distribution server (for details on setting this up, see below), but please note that this is not a requirement - it is completely acceptible to retrieve the relevant files (listed below) by any other means, such as shared physical media. 

  1. Change directories to the mount path of the SD card (if you just completed the SD card setup, this will be the path that `udisksctl` reports).

  1. Store the hostname of the server in a bash variable called `ACADIA_FIRMWARE_SERVER`. In RSL, this is `barharbor.stdusr.yale.internal`, so you should run `export ACADIA_FIRMWARE_SERVER="barharbor.stdusr.yale.internal"`.

  1. Retrieve the latest firmware image by running the following (note that this must be run as one single command, not one line at a time):

  ```
  ftp -i -n $ACADIA_FIRMWARE_SERVER <<EOS
    user anonymous none
    cd firmware-latest
    get BOOT.BIN
    get image.ub
    get boot.scr
    bye
  EOS
  ```

1. Copy the boot configuration script from the Acadia directory by running `cp acadia/petalinux/autostart.sh .`. The path will need to be modified according to where you downloaded this repository on your PC.

1. The hostname and MAC address of the board's Ethernet connection need to be changed at boot. Run the following to insert your allocated hostname and MAC address into the autostart script (talk to Billy to choose these values from a list of reserved names registered with Yale ITS):

```
sed -i -e "s/customhostname/$HOSTNAME/g" -e "s/custommac/$MAC/g" autostart.sh
```

Either replace `$HOSTNAME` and `$MAC` with the appropriate values or populate these bash variables beforehand by running `export HOSTNAME=...; export MAC=...`.

1. Change directories back to your home directory.

1. Ensure that everything was properly committed to the disk by running `sync`.

1. Unmount the card by running `udisksctl unmount -b /dev/sdx1`.

1. Remove the card from the PC, insert it into the ZCU216, and power it on.

### Updating firmware

On the host PC, enter the acadia directory and run `./misc/remote_install.sh --firmware --ip IP` where `IP` is the domain name or IP address of the board. This will update the firmware on the SD card of the board, and then install the `acadia` software (meaning that the steps below can be skipped). If you are located outside of RSL, you will need to update the `FIRMWARE_FTP_SERVER` variable defined at the top of `remote_install.sh`.

### Initial software installation

This will need to be carried out anytime the board is power cycled. On your host PC, enter the acadia directory and run `./misc/remote_install.sh --initial --ip IP` where `IP` is the domain name or IP address of the board. This will automatically deploy and install the `acadia` Python and C libraries, as well as configure the clocking system to its default settings.

## Building firmware from source

The following instructions establish a workflow for building an FPGA bitstream and Linux image from source. This is an advanced procedure only required when pre-built firmware is not available.

### Requirements
1. Vivado 2023.2 with a valid license for the RFSoC Gen 3 devices (included with ZCU216 purchase).
1. Xilinx PetaLinux Tools
1. The PetaLinux Tools directory is available at the environment variable `PETALINUX_TOOLS`
1. The ZCU216 board support package (BSP) for PetaLinux has been downloaded locally
1. The Xilinx DTG source repository is downloaded locally and checked out to the 2023.2 branch, which can be obtained by running `git clone -b xlnx_rel_v2023.2 https://github.com/Xilinx/device-tree-xlnx`

### Build Procedure

1. Create and build an FPGA bitstream.

   1. Open a Python console and execute the following:

   ```
   from acadia.firmware import Firmware
   from acadia.firmware_configurations import CONFIG_200
   project_dir = "acadia-build"
   f = Firmware(CONFIG_200)
   f.write(project_dir)
   ```

   1. Create a Vivado project by executing the command printed above.

   1. The previous step will leave you at the Vivado command line. Launch the build by running `launch_runs -to_step write_bitstream -jobs 8 impl_1`.

   1. After a minute or so and a lot of printed output, you'll be returned to the Vivado command line. The build is NOT complete; it's simply running in the background. Wait for it to finish by running `wait_on_run impl_1`. The build could take anywhere from 30 minutes to 2 hours to complete depending on your PC hardware.

   1. When the build finishes you'll be returned to the Vivado command line. Run the following to verify that it met timing:

   ```
   open_run impl_1
   set timing_report [report_timing_summary -no_header -no_detailed_paths -return_string]
   if {! [string match -nocase {*timing constraints are met*} $timing_report]} {
      error "ERROR: timing not met"
      return -code error
   }
   ```

   1. Export a hardware configuration file by running the following at the Vivado command line:

   ```
   write_hw_platform -fixed -include_bit -force -file acadia-build/acadia_bd_wrapper.xsa
   ```

   1. If you do not need to update the Petalinux image and only need to load the new bitstream into the FPGA, you can do this using the Vivado hardware manager by running:

   ```
   open_hw_manager
   connect_hw_server -allow_non_jtag
   open_hw_target
   set_property PROGRAM.FILE {acadia-build/acadia.runs/impl_1/acadia_bd_wrapper.bit} [get_hw_devices xczu49dr_0]
   set_property PROBES.FILE {acadia-build/acadia.runs/impl_1/acadia_bd_wrapper.ltx} [get_hw_devices xczu49dr_0]
   set_property FULL_PROBES.FILE {acadia-build/acadia.runs/impl_1/acadia_bd_wrapper.ltx} [get_hw_devices xczu49dr_0]
   current_hw_device [get_hw_devices xczu49dr_0]
   refresh_hw_device [lindex [get_hw_devices xczu49dr_0] 0]
   current_hw_device [get_hw_devices arm_dap_1]
   refresh_hw_device -update_hw_probes false [lindex [get_hw_devices arm_dap_1] 0]
   current_hw_device [get_hw_devices xczu49dr_0]
   program_hw_device [get_hw_devices xczu49dr_0]
   ```

1. Build PetaLinux and create a bootable image.

   1. Modify `petalinux/configure_petalinux.sh` so that the directories are correct for your system.

   1. Create the Petalinux project by running `petalinux/configure_petalinux.sh`.

   1. Change directories into the Petalinux project.

   1. Load all the necessary environment variables by running `source $PETALINUX_TOOLS/settings.sh`, where `$PETALINUX_TOOLS` takes on the same value as it did in `configure_petalinux.sh`.

   1. Build the kernel, bootloader, and PMU firmware.
      ```
      petalinux-build
      petalinux-build -c bootloader
      petalinux-build -c fsbl
      petalinux-build -c pmufw
      ```

   1. Package the build into a bootable image with the new FPGA bitstream
      ```
      cd images/linux
      petalinux-package --boot --format BIN --fsbl zynqmp_fsbl.elf --fpga system.bit --u-boot
      ```

Once this is complete, load the SD card with the image by following the steps above in "First-time SD card preparation", but rather than pulling the firmware files from the server over FTP, copy them onto the SD card from the directory `images/linux` in the Petalinux project.

## Setting up a firmware distribution server

For a lab environment with multiple Acadia systems, updating firmware manually can be cumbersome. Because they are somewhat large (a few hundred MB), distributing the firmware in a convenient (and automation-friendly) way is non-trivial; they're too large for Yale's Git servers, and may be for yours as well. Therefore, Acadia's default means of distributing firmware is to host the files on a local FTP server. Note that this is an explicit choice to favor convenience over security; FTP transfers data in the clear, and the server will be configured to allow anonymous connections. This procedure should only be followed for a machine on a local intranet or in some other secure environment; proceed at your own risk. 

1. On a machine designated as the distribution server, install the FTP server daemon using `sudo apt install vsftpd`.

1. Configure the server to allow anonymous connections by editing `/etc/vsftpd.conf` (as root) and uncommenting/adding the following line: `anonymous_enable=YES`

1. Restart the FTP server by running `sudo service vsftpd restart`.

1. By default, the FTP server will have its root directory be `/srv/ftp`. In this directory, create a folder named `firmware-latest`.

1. Locate the firmware files BOOT.BIN, boot.scr, and image.ub. These can be retrieved either from a Petalinux build (in the `images/linux` directory) or from the SD card of another system.

1. Place the firmware files in the `firmware-latest` folder.

