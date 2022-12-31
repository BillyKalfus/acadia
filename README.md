# The Acadia Quantum Control System

William Kalfus and Jacob Curtis

Yale University, 2023

## Description

The Acadia Quantum Control ecosystem is intended to provide a modern, simple, and unified framework for integrating real-time signal synthesis and processing with hardware compute resources. The framework was developed to target the ZCU216 RFSoC evaluation board but straightforwardly extends to other hardware. 

## Python installation

### Requirements

This software requires Python >= 3.7.

### Installation

Install the Python library using the standard `distutils` install script:

```
python3 setup.py install
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

1. Export a hardware description file from Vivado
   1. File -> Export -> Export Hardware
   2. Follow the steps, check the box "include bitstream"
   3. Make a note of the directory where this is exported
2. Create device tree files to map the device memory network into the PS image.

```
$PETALINUX/tools/xsct/bin/xsct
> hsi open_hw_design <xsa file>
```
Make a note of the hardware design name, which will be printed after after the line starting with `hsi::open_hw_design: Time …`
```
> hsi set_repo_path <path-to-device-tree-xlnx repo>
> hsi create_sw_design device-tree -os device_tree -proc psu_cortexa53_0
> hsi generate_target -dir <directory where dts/dtsi files should be generated to>
> hsi close_hw_design <name of hardware design>
> exit
```

3. Create a PetaLinux project from the Xilinx BSP and configure it with the new bitstream
   1. Create a folder to make the project in and change directories into it.
   2. Apply the PetaLinux environment settings for your current shell session.
      ```
      source $PETALINUX/settings.sh
      ```
      This will probably complain about not having a TFTP server, ignore this

   3. Create a Petalinux project from the ZCU216 BSP.
      ```
      petalinux-create -t project -s xilinx-zcu216-2020.2-bsp.bsp
      cd xilinx-evaltool-zcu216-2020.2-bsp
      ```
   4. Configure the Petalinux project with the hardware description exported from Vivado
      ```
      petalinux-config --get-hw-description=<path to directory with hw description file>
      ```
      Exit the config menu that pops up, if it asks you to save say yes
   5. Copy the device tree files generated previously into the Petalinux project
     1. Copy all the dts/dtsi files generated into `components/plnx_workspace/device-tree/device-tree`
     2. Copy the `include` folder in that same directory as well

4. Configure Linux settings and packages  

  1. Change hostname, product name, firmware version
     1. `petalinux-config`
     2. Go to Firmware Version Configuration
  2. Add Linux packages to the image
     1. `petalinux-config -c rootfs`
     2. Add the following packages:
        ```
        Filesystem Packages -> base -> i2ctools -> <all>
        Filesystem Packages -> base -> init-ifupdown -> init-ifupdown
        Filesystem Packages -> base -> opkg -> opkg
        Filesystem Packages -> base -> tar -> tar
        Filesystem Packages -> console -> utils -> grep -> <all>
        Filesystem Packages -> console -> utils -> less -> <all>
        Filesystem Packages -> console -> utils -> screen -> <all>
        Filesystem Packages -> console -> utils -> sed -> <all>
        Filesystem Packages -> console -> utils -> unzip -> <all>
        Filesystem Packages -> console -> utils -> vim -> <all>
        Filesystem Packages -> console -> utils -> zip -> <all>
        Filesystem Packages -> devel -> autoconf -> autoconf
        Filesystem Packages -> devel -> automake -> automake
        Filesystem Packages -> devel -> binutils -> binutils
        Filesystem Packages -> devel -> bison -> bison
        Filesystem Packages -> devel -> expect -> expect
        Filesystem Packages -> devel -> flex -> flex
        Filesystem Packages -> devel -> make -> make
        Filesystem Packages -> devel -> python -> python3-numpy -> <all>
        Filesystem Packages -> libs -> libmetal -> <all>
        Filesystem Packages -> misc -> packagegroup-core-buildessential -> <all>
        Filesystem Packages -> misc -> python3 -> python3, python3-io, python3-pprint, python3-datetime, python3-modules, python3-numbers, python3-pyvenv, python3-netclient, python3-netserver, python3-math, python3-asyncio, python3-core, python3-threading, python3-misc, python3-mmap, python3-json, python3-distutils, python3-multiprocessing, python3-dev, libpython3, python3-logging, python3-ctypes, python3-compile, python3-pickle, python3-dbg, python3-debugger
        Filesystem Packages -> misc -> python3-setuptools -> python3-setuptools
        Filesystem Packages -> misc -> rpm -> rpm, rpm-build
        ```
     3. Press / to search for any additional desired packages
     4. Under "PetaLinux RootFS Settings" you can change the root user and password
     5. Exit and Save
     6. TODO: look into automatic package configuration using build/misc/rootfs_config/Kconfig
     7. Open `project-spec/meta-user/conf/layer.conf` in your favorite text editor
     8. At the end add:
        ```
        IMAGE_INSTALL_append = " cmake python3-pip python3-pybind11 python3-cython python3-cffi python3-jupyterlab python3-matplotlib python3-pillow python3-pydot python3-psutil python3-pandas python3-ipywidgets"
        ```
5. Clean up default device tree config
   1. Open `project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi` in your favorite text editor
   2. Remove everything between `plmem: ` and the `CAUTION` comment near the bottom EXCEPT for the leftmost-aligned `};` (you may need to re-add it if you accidentally delete it)

6. Build PetaLinux and create a bootable image
   1. Build the kernel, bootloader, and PMUFW
      ```
      petalinux-build
      petalinux-build -c bootloader
      petalinux-build -c pmufw
      ```
      The first one will take some time and all of them will complain that it failed to copy built images to tftpboot, ignore this

   2. Package the build into a bootable image with the new FPGA bitstream
      ```
      cd images/linux
      petalinux-package --boot --format BIN --fsbl zynqmp_fsbl.elf --fpga system.bit --u-boot
      ```
   3. Prepare SD card for boot
      1. Copy `BOOT.BIN`, `image.ub`, and `boot.scr` to an SD card formatted as FAT32
      2. Make a file on the root of the SD card called `autostart.sh` with the following contents (and anything else you may want to add which will run when the board boots):
      ```
      #!/bin/sh
      ifconfig -a | grep eth0
      RESULT=$?
      if [ $RESULT -eq 0 ]; then
        ifconfig eth0 192.168.0.2
      fi
      ```

7. Insert SD card into the socket on the ZCU216 and turn on the power switch.
