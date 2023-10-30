#!/bin/sh

HOSTNAME=billy-zcu216
MAC=76:54:C6:67:BC:BB
IP=192.168.2.69

# Set the hostname
hostname $HOSTNAME

# Patch the network interfaces file to update the hostname and MAC address
echo "--- interfaces.old      2023-09-23 21:16:56.996001553 +0000" >> network.patch
echo "+++ interfaces.new      2023-09-23 21:19:12.276001764 +0000" >> network.patch
echo "@@ -16,6 +16,9 @@"  >> network.patch
echo " # Wired or wireless interfaces" >> network.patch
echo " auto eth0" >> network.patch
echo " iface eth0 inet dhcp" >> network.patch
echo "+       hwaddress ether $MAC" >> network.patch
echo "+       hostname $HOSTNAME" >> network.patch
echo "+ " >> network.patch
echo " iface eth1 inet dhcp" >> network.patch
echo " " >> network.patch
echo " # Ethernet/RNDIS gadget (g_ether)" >> network.patch

patch -ru /etc/network/interfaces < network.patch

rm network.patch

# Restart the ethernet link
ifconfig eth0 down
sleep 2;
if [ -n "$MAC" ]; then
	ifconfig eth0 hw ether $MAC
fi
sleep 1;

/etc/init.d/networking restart

# If we supplied an IP address, set it
if [ -n "$IP" ]; then
	ifconfig eth0 $IP
fi

# Start a Jupyter lab
screen -dm bash -c "jupyter lab --no-browser --port=8070 --allow-root --ip=\"*\" --LabApp.token='' --LabApp.password=''"
