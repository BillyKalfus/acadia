# The Acadia Microwave Instrument

William Kalfus and Jacob Curtis

Yale University, 2023

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
pip3 install -e acadia/pyacadia[host]
```

### Development Environment

This software supports deployment and runtime management from any Python terminal. However, many users would like to visualize data in real-time, even if just to confirm that deployment is progressing satisfactorily. This is implemented in Acadia through `IPython` and `ipywidgets`, and visualization is supported in any front-end capable of rendering their outputs, such as Jupyter notebooks. 

We primarily encourage the use of this software through VS Code, which may be installed [here](https://code.visualstudio.com/download).

## ZCU216 Configuration

### First-time Setup

### ZCU216 firmware

For ZCU216 hardware connected to the internet, the firmware can be updated with the following procedure:

```
cd /mnt/sd-mmcblk0p1
wget https://git.yale.edu/RSL/acadia/releases/latest/image.zip
unzip -fo image.zip
```

The new firmware will then be loaded the next time the board is rebooted.

### ZCU216 software installation

1. Copy this repository onto your board.

1. Install the hardware drivers.

```
python3 acadia/pyacadia/install_drivers.py
```

1. Install the Python libraries using `pip`.

```
pip3 install -e acadia/pyacadia
```

## Building a Linux image with integrated FPGA bitstream (Advanced)

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

1. Create and build a bitstream by following the notebook `tutorials/00_building_firmware.ipynb`

1. Export a hardware description file from Vivado
   1. File -> Export -> Export Hardware
   1. Follow the steps, check the box "include bitstream"
1. Modify `petalinux/configure_petalinux.sh` so that the directories are correct for your system
1. Create the Petalinux project by running `petalinux/configure_petalinux.sh` 
1. Change directories into the Petalinux project

1. Build PetaLinux and create a bootable image
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

1. Prepare SD card for boot

   1. Ensure that your SD card is formatted as FAT32.

   1. From within the PetaLinux project's `images/linux` directory, copy `BOOT.BIN`, `image.ub`, and `boot.scr` to the card.

   1. From the `petalinux` directory of this repo, copy `autostart.sh` to the card, making any changes necessary for your network. Note that this doesn't need to be done every time, as no part of the build touches this file; if you had a copy on your card already that was working, it's unlikely that this needs to be changed!
      

1. Insert SD card into the socket on the ZCU216 and turn on the power switch.
