#!/bin/bash

REPO_DIR="/home/billy/device-tree-xlnx"
VIVADO_PROJ_DIR="/home/billy/acadia-build-slow"
BSP="/home/billy/xilinx-zcu216-v2020.2-final.bsp"
BSP_NAME="xilinx-zcu216-2020.2"
SRC_DIR="/home/billy/acadia/petalinux"
PETALINUX_TOOLS="/home/billy/PetaLinux"

# Load petalinux tools
source $PETALINUX_TOOLS/settings.sh

# Generate the device tree files
$PETALINUX/tools/xsct/bin/xsct -eval "hsi open_hw_design $VIVADO_PROJ_DIR/acadia_bd_wrapper.xsa; hsi set_repo_path $REPO_DIR; hsi create_sw_design device-tree -os device_tree -proc psu_cortexa53_0; hsi generate_target -dir $VIVADO_PROJ_DIR/dts; hsi close_hw_design acadia_bd_wrapper"

# Create the petalinux project
cd $VIVADO_PROJ_DIR
petalinux-create -t project -s $BSP
cd $BSP_NAME

# Configure the project with the hardware description
petalinux-config --get-hw-description=$VIVADO_PROJ_DIR

# Copy the device tree files and autostart package into the project
cp -r $VIVADO_PROJ_DIR/dts/* components/plnx_workspace/device-tree/device-tree
cp -r $SRC_DIR/trd-autostart project-spec/meta-user/recipes-apps

# Replace the system-user.dtsi device tree file
cp $SRC_DIR/system-user.dtsi project-spec/meta-user/recipes-bsp/device-tree/files

# Add the packages 
cat $SRC_DIR/packages.txt >> project-spec/meta-user/conf/user-rootfsconfig

