# The Acadia Quantum Control System

William Kalfus and Jacob Curtis

Yale University, 2023

## Description

The Acadia Quantum Control ecosystem is intended to provide a modern, simple, and unified framework for integrating real-time signal synthesis and processing with hardware compute resources. The framework was developed to target the ZCU216 RFSoC evaluation board but straightforwardly extends to other hardware. 


## Installation

### ZCU216 firmware

For ZCU216 hardware connected to the internet, the firmware can be updated with the following procedure:

```
cd /mnt/sd-mmcblk0p1
wget https://git.yale.edu/RSL/acadia/releases/latest/image.zip
unzip -fo image.zip
```

The new firmware will then be loaded the next time the board is rebooted.

### ZCU216 software installation

First the first install, you must clone the Xilinx embeddedsw library onto the board's SD card so that the RF drivers can be built against it. Log into the board and execute

```
cd /mnt/sd-mmcblk0p1
git clone https://github.com/Xilinx/embeddedsw.git
cd embeddedsw
git checkout release-2020.2
```

Then, after cloning this repository on the board, execute

```
pip3 install -e acadia/pyacadia --global-option=install_drivers
```

## Building a Linux image with integrated FPGA bitstream

### Requirements
1. Vivado 2020.2 with a valid license for the RFSoC Gen 3 devices (included with ZCU216 purchase).
1. Xilinx PetaLinux Tools
1. The PetaLinux Tools directory is available at the environment variable `PETALINUX`
1. The Xilinx DTG source repository is downloaded locally and checked out to the 2020.2 branch

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
1. Modify `petalinux/configure_petalinux.sh` so that the directories are correct for your system
1. Create the Petalinux project by running `petalinux/configure_petalinux.sh` 
1. Change directories into the Petalinux project

1. Build PetaLinux and create a bootable image
   1. Build the kernel. This will take a while and then fail.
      ```
      petalinux-build
      ```

   1. Apply a patch to LAPACK by running
      ```
      patch -ru -d build/tmp/work/aarch64-xilinx-linux/lapack/3.8.0-r0/recipe-sysroot-native/usr/share/cmake-3.15/Modules/FortranCInterface < project-spec/meta-scipy/recipes-devtools/cmake/cmake-native/0001-FortranCInterface-Fix-broken-search-for-test-exe-whe.patch
      ```

   1. Run `petalinux-build` again. At the end, it should say that it successfully built the project but failed to copy built images to a TFTP directory; ignore this.

   1. Build the bootloader and PMU firmware.
      ```
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
