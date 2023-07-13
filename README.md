# The Acadia Quantum Control System

William Kalfus and Jacob Curtis

Yale University, 2023

## Description

The Acadia Quantum Control ecosystem is intended to provide a modern, simple, and unified framework for integrating real-time signal synthesis and processing with hardware compute resources. The framework was developed to target the ZCU216 RFSoC evaluation board but straightforwardly extends to other hardware. 

## Python installation

### Requirements

This software requires Python >= 3.7.

### Installation

This package may be installed on any processor platform if the RF data converter drivers are not required by executing

```
pip3 install -e acadia/pyacadia
```

On the ZCU216 you should execute

```
pip3 install -e acadia/pyacadia --global-option=install_drivers
```

## Building the FPGA logic for the ZCU216

### Requirements
1. Vivado 2020.2 with a valid license for the RFSoC Gen 3 devices (included with ZCU216 purchase).

## Building a Linux image with integrated FPGA bitstream

### Requirements
1. Vivado 2020.2 and PetaLinux Tools are installed and properly licensed
2. The PetaLinux Tools directory is available at the environment variable `PETALINUX`
3. The Xilinx DTG source repository is downloaded locally and checked out to the 2020.2 branch

```
git clone https://github.com/Xilinx/device-tree-xlnx
cd device-tree-xlnx
git checkout xilinx-v2020.2
cd ..
```

### Build Procedure

1. Create and build a bitstream by following the notebook `tutorials/00_building_firmware.ipynb`

1. Export a hardware description file from Vivado
   1. File -> Export -> Export Hardware
   1. Follow the steps, check the box "include bitstream"
1. Create the Petalinux project by running `petalinux/configure_petalinux.sh` 
1. Change directories into the Petalinux project
1. Configure the rootfs
   1. Run `petalinux-config -c rootfs`
   1. Enter `apps` and enable `trd-autostart`
   1. Go back to the main menu
   1. Enter `user packages` and enable everything
   1. Exit and save the configuration

1. Build PetaLinux and create a bootable image
   1. Build the kernel, bootloader, and PMUFW
      ```
      petalinux-build
      petalinux-build -c bootloader
      petalinux-build -c fsbl
      petalinux-build -c pmufw
      ```
      The first one will take some time and all of them will complain that it failed to copy built images to tftpboot, ignore this

   1. Package the build into a bootable image with the new FPGA bitstream
      ```
      cd images/linux
      petalinux-package --boot --format BIN --fsbl zynqmp_fsbl.elf --fpga system.bit --u-boot
      ```
   1. Prepare SD card for boot
      1. Copy `BOOT.BIN`, `image.ub`, and `boot.scr` to an SD card formatted as FAT32
      1. Make a file on the root of the SD card called `autostart.sh` with the following contents (and anything else you may want to add which will run when the board boots):
      ```
      #!/bin/sh

      hostname <HOSTNAME>

      ifconfig -a | grep eth0
      RESULT=$?
      if [ $RESULT -eq 0 ]; then
         ifconfig eth0 down
         ifconfig eth0 hw ether <MAC ADDRESS>
         ifconfig eth0 up
      fi

      screen -dm bash -c "jupyter lab --no-browser --port=8070 --allow-root --ip=\"*\" --LabApp.token='' --LabApp.password=''"
      ```

1. Insert SD card into the socket on the ZCU216 and turn on the power switch.
