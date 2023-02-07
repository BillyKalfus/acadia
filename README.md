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
      petalinux-create -t project -s xilinx-zcu216-v2020.2-final.bsp
      cd xilinx-zcu216-2020.2
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
     1. Edit `project-spec/meta-user/conf/user-rootfsconfig` and add the following:
     ```
     CONFIG_i2c-tools
     CONFIG_i2c-tools-dev
     CONFIG_i2c-tools-misc
     CONFIG_init-ifupdown
     CONFIG_opkg
     CONFIG_tar
     CONFIG_grep
     CONFIG_less
     CONFIG_screen
     CONFIG_sed
     CONFIG_unzip
     CONFIG_vim
     CONFIG_zip
     CONFIG_autoconf
     CONFIG_automake
     CONFIG_binutils
     CONFIG_bison
     CONFIG_expect
     CONFIG_flex
     CONFIG_make
     CONFIG_cmake
     CONFIG_libmetal
     CONFIG_libmetal-dev
     CONFIG_packagegroup-core-buildessential
     CONFIG_rpm
     CONFIG_rpm-build
     CONFIG_util-linux-mkfs
     CONFIG_util-linux-fdisk
     CONFIG_util-linux-bash-completion
     CONFIG_util-linux-umount
     CONFIG_util-linux-mount
     CONFIG_util-linux-lscpu
     CONFIG_python3
     CONFIG_python3-numpy
     CONFIG_python3-io
     CONFIG_python3-pprint
     CONFIG_python3-datetime
     CONFIG_python3-modules
     CONFIG_python3-numbers
     CONFIG_python3-pyvenv
     CONFIG_python3-netclient
     CONFIG_python3-netserver
     CONFIG_python3-math
     CONFIG_python3-asyncio
     CONFIG_python3-core
     CONFIG_python3-threading
     CONFIG_python3-misc
     CONFIG_python3-mmap
     CONFIG_python3-json
     CONFIG_python3-distutils
     CONFIG_python3-multiprocessing
     CONFIG_python3-dev
     CONFIG_libpython3
     CONFIG_python3-logging
     CONFIG_python3-ctypes
     CONFIG_python3-compile
     CONFIG_python3-pickle
     CONFIG_python3-dbg
     CONFIG_python3-debugger
     CONFIG_python3-setuptools
     CONFIG_python3-pip
     CONFIG_python3-pybind11
     CONFIG_python3-cython
     CONFIG_python3-cffi
     CONFIG_python3-jupyterlab
     CONFIG_python3-matplotlib
     CONFIG_python3-pillow
     CONFIG_python3-pydot
     CONFIG_python3-psutil
     CONFIG_python3-pandas
     CONFIG_python3-ipywidgets
     ```
     2. Run `petalinux-config -c rootfs`
     3. Enter the `user-packages` submenu and enable the packages added in the previous step.
     
5. Build PetaLinux and create a bootable image
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

6. Insert SD card into the socket on the ZCU216 and turn on the power switch.
