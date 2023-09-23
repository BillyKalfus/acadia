#!/bin/bash

REPO_DIR="/home/billy/device-tree-xlnx"
VIVADO_PROJ_DIR="/home/billy/acadia-build"
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

# Enable the packages
# For this we have to add "=y" to every line in packages.txt
cat $SRC_DIR/packages.txt | while read line
do
    echo "$line"=y >> project-spec/configs/rootfs_config
done

# Download the scipy layer
cd project-spec
git clone -b zeus https://github.com/gpanders/meta-scipy 
cd ..

# Add the layer as a user layer
echo CONFIG_USER_LAYER_0=\""$VIVADO_PROJ_DIR"/"$BSP_NAME"/project-spec/meta-scipy\" >> project-spec/configs/config
echo CONFIG_USER_LAYER_1=\"\" >> project-spec/configs/config

# Enable scipy and lapack
echo CONFIG_python3-scipy >> project-spec/meta-user/conf/user-rootfsconfig
echo CONFIG_lapack >> project-spec/meta-user/conf/user-rootfsconfig
echo CONFIG_python3-scipy=y >> project-spec/configs/rootfs_config
echo CONFIG_lapack=y >> project-spec/configs/rootfs_config

# Add recipes
echo SIGGEN_UNLOCKED_RECIPES += \"gcc-cross-aarch64 libgcc-initial\" >> project-spec/meta-user/conf/petalinuxbsp.conf
echo FORTRAN_forcevariable = \",fortran\" >> project-spec/meta-user/conf/petalinuxbsp.conf
echo RUNTIMETARGET_append_pn-gcc-runtime = \" libquadmath\" >> project-spec/meta-user/conf/petalinuxbsp.conf
