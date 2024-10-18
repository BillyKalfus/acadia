# The Acadia Microwave Instrument

William Kalfus

Yale University, 2024

## Description

The Acadia platform is intended to provide a modern, simple, and unified framework for integrating real-time signal synthesis and processing with hardware compute resources. The framework was developed to target the ZCU216 RFSoC evaluation board but straightforwardly extends to other hardware. 

## Host Computers

Host computers are responsible for deploying procedures onto remote targets, receiving and archiving any data from them, and potentially rendering any live outputs during the procedure.

### OS and Software Requirements

Acadia only supports host computers using an Ubuntu or Debian-based distribution of Linux, either natively or through the Windows Subsystem for Linux (WSL). See [this link](https://learn.microsoft.com/en-us/windows/wsl/install) for information about how to install WSL on Windows machines. This software was developed using Ubuntu 22.04.3 LTS, though any reasonably modern distribution should function properly. Acadia has also been known to function on recent versions of Mac OS, though compatibility is not guaranteed.

The host computer must have `python>=3.8` along with the packages `python3-pip` and (optionally) `python3-venv`. These can be installed from the Linux command line as

```
sudo apt update
sudo apt install python3-pip python3-venv
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

## ZCU216 Configuration

### First-time SD card preparation and firmware installation

Please note that the first installation of Acadia must be carried out using a Linux-based machine to which you have root access (it is currently unknown whether this can be performed on Windows or through WSL). Some Linux machines are available in RSL, talk to Billy for connection information. You will need a microSD card onto which the boot image will be installed; this will erase all information on the card. This will install the latest firmware, so when this step is carried out you can skip the "Updating firmware" section.

1. Download this repository somewhere onto the PC. 

1. Use a microSD card adapter to plug the card into the PC. 

1. Determine the device path of the card by running `lsblk` at the Linux command line. This will print out one line for each disk and partition in the system, which contains a path like `/dev/sdx` and a device size. Given the device sizes, determine which path corresponds to the SD card. If the disk is already partitioned, there may be a path with a number at the end such as `/dev/sdx1`; ignore this.

1. Use `fdisk` to wipe the card and create a partition for the boot image. We'll create a partition that's only 1GB in size due to bootloader limitations on the FPGA, but you may create additional partitions for data if you like. At the command line, run the following:

```
sudo fdisk /dev/sdx # Replace this with the path to your card
```

1. Confirm that the partition was created by running `lsblk`. Now, under the same device path, you should see an entry like `/dev/sdx1` that's listed as being 1GB in size.

1. Format the partition to have a FAT32 filesystem by running `sudo mkfs -t fat /dev/sdx1`.

1. Mount the filesystem on the PC by running `udisksctl mount -b /dev/sdx1`. If this completes successfully, it will tell you the path at which the filesystem was mounted. 

1. Change directories to the path that `udisksctl` reported.

1. Retrieve the latest firmware image by running the following (note that this must be run as one single command, not one line at a time):

```
ftp -i -n barharbor.stdusr.yale.internal <<EOS
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

On the host PC, enter the acadia directory and run `./misc/remote_install.sh --firmware --ip IP` where `IP` is the domain name or IP address of the board. This will update the firmware on the SD card of the board, and then install the `acadia` software (meaning that the steps below can be skipped).

### Initial software installation

This will need to be carried out anytime the board is power cycled. On your host PC, enter the acadia directory and run `./misc/remote_install.sh --initial --ip IP` where `IP` is the domain name or IP address of the board. This will automatically deploy and install the `acadia` Python and C libraries, as well as configure the clocking system to its default settings.

## Building firmware from source

The following instructions establish a workflow for building an FPGA bitstream and Linux image from source. This is an advanced procedure only required when pre-built firmware is not available.

### Requirements
1. Vivado 2023.2 with a valid license for the RFSoC Gen 3 devices (included with ZCU216 purchase).
1. Xilinx PetaLinux Tools
1. The PetaLinux Tools directory is available at the environment variable `PETALINUX`
1. The Xilinx DTG source repository is downloaded locally and checked out to the 2023.2 branch

```
git clone https://github.com/Xilinx/device-tree-xlnx
cd device-tree-xlnx
git checkout xilinx-v2023.2
cd ..
```

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
