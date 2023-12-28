#!/bin/bash

VIVADO_BIN_DIR="/tools/Xilinx/Vivado/2020.2/bin"
VIVADO_PROJ_DIR="/home/billy/acadia-build"

# Create a bin file with bootgen for dynamically updating firmware
rm $VIVADO_PROJ_DIR/acadia_bd_wrapper.bif
echo "all:" >> $VIVADO_PROJ_DIR/acadia_bd_wrapper.bif
echo "{"  >> $VIVADO_PROJ_DIR/acadia_bd_wrapper.bif
echo "    acadia_bd_wrapper.bit" >> $VIVADO_PROJ_DIR/acadia_bd_wrapper.bif
echo "}"  >> $VIVADO_PROJ_DIR/acadia_bd_wrapper.bif

$VIVADO_BIN_DIR/bootgen -image acadia_bd_wrapper.bif -arch zynqmp -w on -process_bitstream bin
