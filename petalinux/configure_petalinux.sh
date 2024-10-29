#!/bin/bash

DEVICE_TREE_REPO_DIR="/home/billy/device-tree-xlnx"
VIVADO_PROJ_DIR="/home/billy/acadia-build"
BSP="/home/billy/xilinx-zcu216-v2023.2.bsp"
BSP_NAME="xilinx-zcu216-2023.2"
ACADIA_REPO_DIR="/home/billy/acadia"
PETALINUX_TOOLS="/home/billy/petalinux2023.2"

# Load petalinux tools
source $PETALINUX_TOOLS/settings.sh

# Generate the device tree files
$PETALINUX_TOOLS/tools/xsct/bin/xsct -eval "hsi open_hw_design $VIVADO_PROJ_DIR/acadia_bd_wrapper.xsa; hsi set_repo_path $DEVICE_TREE_REPO_DIR; hsi create_sw_design device-tree -os device_tree -proc psu_cortexa53_0; hsi generate_target -dir $VIVADO_PROJ_DIR/dts; hsi close_hw_design acadia_bd_wrapper"

# Create the petalinux project
cd $VIVADO_PROJ_DIR
petalinux-create -t project -s $BSP
cd $BSP_NAME

# Configure the project with the hardware description
petalinux-config --get-hw-description=$VIVADO_PROJ_DIR --silentconfig

# Remove the extra demo files that come with the BSP
rm -rf pre-built
rm -rf hardware

# Instruct the build to use the correct rootfs
sed -i -e 's/CONFIG_SUBSYSTEM_INITRAMFS_IMAGE_NAME="petalinux-initramfs-image"/CONFIG_SUBSYSTEM_INITRAMFS_IMAGE_NAME="petalinux-image-minimal"/g' project-spec/configs/config

# Enable debug tweaks so that we can log in as root
echo CONFIG_imagefeature-debug-tweaks=y >> project-spec/configs/rootfs_config

# Set the passwords
sed -i -e 's/CONFIG_ADD_EXTRA_USERS="[a-zA-Z:;\-]*"/CONFIG_ADD_EXTRA_USERS="root:root;petalinux:petalinux;"/g' project-spec/configs/rootfs_config

# Copy the device tree files into the project
cp -r $VIVADO_PROJ_DIR/dts/* components/plnx_workspace/device-tree/device-tree

# Replace the system-user.dtsi device tree file
cp $ACADIA_REPO_DIR/petalinux/system-user.dtsi project-spec/meta-user/recipes-bsp/device-tree/files

# Create an autostart system
petalinux-create -t apps --template install -n autostart --enable
cp -r $ACADIA_REPO_DIR/petalinux/autostart/* project-spec/meta-user/recipes-apps/autostart

# Add the packages
cat $ACADIA_REPO_DIR/petalinux/packages.txt >> project-spec/meta-user/conf/user-rootfsconfig

# Enable the packages
# For this we have to add "=y" to every line in packages.txt
cat $ACADIA_REPO_DIR/petalinux/packages.txt | while read line
do
    echo "$line"=y >> project-spec/configs/rootfs_config
done

# Set OpenSSH as the SSH server
# We first need to disable dropbear
sed -i -e 's/CONFIG_packagegroup-core-ssh-dropbear/#CONFIG_packagegroup-core-ssh-dropbear/g' -e 's/CONFIG_imagefeature-ssh-server-dropbear/#CONFIG_imagefeature-ssh-server-dropbear/g' project-spec/configs/rootfs_config

# Now add everything for openssh
echo CONFIG_openssh=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-ssh=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-sftp=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-keygen=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-dbg=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-dev=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-misc=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-sshd=y >> project-spec/configs/rootfs_config
echo CONFIG_openssh-scp=y >> project-spec/configs/rootfs_config
echo CONFIG_imagefeature-ssh-server-openssh=y >> project-spec/configs/rootfs_config

# Disable tcf-agent (for some reason this consistently fails to build)
sed -i -e 's/CONFIG_tcf-agent/#CONFIG_tcf-agent/g' project-spec/configs/rootfs_config

# Download the scipy layer
# https://support.xilinx.com/s/question/0D52E00007G0ubzSAB/python-scipy-install-with-petalinux-20202-for-the-zynq7000?language=en_US
# cd project-spec
# git clone -b zeus https://github.com/gpanders/meta-scipy 
# cd ..

# # Add the layer as a user layer
# echo "CONFIG_USER_LAYER_0=\"$VIVADO_PROJ_DIR/$BSP_NAME/project-spec/meta-scipy\"" >> project-spec/configs/config
# echo CONFIG_USER_LAYER_1=\"\" >> project-spec/configs/config

# # Enable scipy and lapack
# echo CONFIG_python3-scipy >> project-spec/meta-user/conf/user-rootfsconfig
# echo CONFIG_lapack >> project-spec/meta-user/conf/user-rootfsconfig
# echo CONFIG_python3-scipy=y >> project-spec/configs/rootfs_config
# echo CONFIG_lapack=y >> project-spec/configs/rootfs_config

# # Add recipes
# echo SIGGEN_UNLOCKED_RECIPES += \"gcc-cross-aarch64 libgcc-initial\" >> project-spec/meta-user/conf/petalinuxbsp.conf
# echo FORTRAN_forcevariable = \",fortran\" >> project-spec/meta-user/conf/petalinuxbsp.conf
# echo RUNTIMETARGET_append_pn-gcc-runtime = \" libquadmath\" >> project-spec/meta-user/conf/petalinuxbsp.conf

# # Add kernel headers
# echo IMAGE_INSTALL_append = \" kernel-devsrc\" >> project-spec/meta-user/conf/petalinuxbsp.conf
# echo CONFIG_kernel-devsrc=y >> project-spec/configs/rootfs_config
