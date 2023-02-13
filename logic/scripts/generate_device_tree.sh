#!/bin/bash
vivado write_hw_platform -fixed -include_bit -force -file /home/billy/acadia-build/acadia_bd_wrapper.xsa
$PETALINUX/tools/xsct/bin/xsct -eval "hsi open_hw_design /home/billy/acadia-build/acadia_bd_wrapper.xsa; hsi set_repo_path /home/billy/device-tree-xlnx; hsi create_sw_design device-tree -os device_tree -proc psu_cortexa53_0; hsi generate_target -dir /home/billy/acadia-build/dts; hsi close_hw_design acadia_bd_wrapper"
cp -r /home/billy/acadia-build/dts/* components/plnx_workspace/device-tree/device-tree
cp -r /home/billy/bsp-testing/xilinx-evaltool-zcu216-2020.2-bsp/project-spec/meta-user/recipes-apps/trd-autostart /home/billy/acadia-build/xilinx-zcu216-2020.2/project-spec/meta-user/recipes-apps