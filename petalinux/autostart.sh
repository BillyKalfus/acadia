#!/bin/sh

hostname billy-zcu216

cp /mnt/sd-mmcblk0p1/interfaces /etc/network/interfaces
cp /mnt/sd-mmcblk0p1/wpa_supplicant.conf /etc/wpa_supplicant.conf

ifconfig -a | grep eth0
RESULT=$?
if [ $RESULT -eq 0 ]; then
#	ifconfig eth0 192.168.2.70
	ifconfig eth0 down
	ifconfig eth0 hw ether 76:54:C6:67:BC:BB
	ifconfig eth0 up
	# rftool
fi

# cp -r /mnt/sd-mmcblk0p1/{pyrfsoc,embeddedsw-master} /home/root/
screen -dm bash -c "jupyter lab --no-browser --port=8070 --allow-root --ip=\"*\" --LabApp.token='' --LabApp.password=''"
