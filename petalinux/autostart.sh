#!/bin/sh

HOSTNAME=customhostname
MAC=custommac
# IP=192.168.2.69  #DHCP for Yale network

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
sleep 2;

# If we supplied an IP address, set it
if [ -n "$IP" ]; then
	ip addr add $IP dev eth0 
fi

# Change SSH settings to speed things up
sed -i -e 's/UsePAM/#UsePAM/g' /etc/ssh/sshd_config
/etc/init.d/sshd restart

# Install acadia drivers
# cd /home/root
# python3 /run/media/mmcblk0p1/acadia/pyacadia/install_drivers.py

# Install acadia library
# pip3 install -e /run/media/mmcblk0p1/acadia/pyacadia
