#!/bin/bash

SCRIPT=$0
INITIAL=false
IP=''

while [[ $# -gt 0 ]]; do
    case $1 in
        --ip)
            IP="$2"
            shift
            shift
            ;;
        --initial)
            INITIAL=true
            shift
            ;;
        *)
            echo "Unknown option $1"
            exit 1
            ;;
    esac
done

if $INITIAL; then
    echo "Copying SSH key..."
    ssh-keygen -f ~/.ssh/known_hosts -R $IP
    ssh-copy-id root@$IP
fi

echo "Killing active screens..."
ssh root@$IP killall screen

echo "Deploying acadia..."
scp -q -r "$(dirname $SCRIPT)/../../acadia" root@$IP:/home/root

echo "Installing pyacadia..."
ssh root@$IP pip3 install -e acadia/pyacadia > /dev/null

if $INITIAL; then
    echo "Installing drivers..."
    ssh root@$IP python3 acadia/pyacadia/install_drivers.py > /dev/null

    echo "Configuring clocks and resetting RAM..."
    ssh root@$IP 'python3 -c "from acadia.system import Acadia; a = Acadia(); a.attach(); a.configure_clocks(); a.reset_plddr0(); a.reset_plddr1();"'
fi

echo "Complete."