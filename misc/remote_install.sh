#!/bin/bash

SCRIPT=$0
INITIAL=false
FIRMWARE=false
FIRMWARE_FTP_SERVER="10.66.231.25"
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
        --firmware)
            FIRMWARE=true
            INITIAL=true
            shift
            ;;
        *)
            echo "Unknown option $1"
            echo "Usage: remote_install.sh --ip IP [--initial] [--firmware]"
            echo "With only an IP address supplied, pyacadia will be deployed and installed."
            echo "Use --initial to set up SSH keys and install drivers and other required libraries that are required for pyacadia, but which do not need to be reinstalled when updating acadia. This is typically used following a power cycle after which the target's memory is wiped."
            echo "Use --firmware to download the latest firmware (the packaged Linux image and FPGA gateware) and deploy it to the target. This option will automatically run the steps for --initial after the new firmware is loaded."
            exit 1
            ;;
    esac
done

# Check for the presence of some required programs
if ! $(which ftp > /dev/null) ; then
    echo "FTP client must be installed to use this script."
    exit 1
fi

if ! $(which expect > /dev/null) ; then
    echo "expect must be installed to use this script."
    exit 1
fi

if ! $(which wget > /dev/null) ; then
    echo "wget must be installed to use this script."
    exit 1
fi

deploy_ssh_key () {
    ssh-keygen -f ~/.ssh/known_hosts -R $IP

    # Copy the key to the remote host
    # This will ask for the password, so we can use an expect script to automatically provide it
    echo "Sending acadia SSH key to target..."
    cmd="ssh-copy-id -f -i $HOME/.ssh/id_acadia -oStrictHostKeyChecking=no root@$IP"
    expect -c "eval spawn $cmd; expect \"password:\"; send \"root\r\"; interact"
}

# In all cases we'll use the dedicated acadia SSH key, so no matter
# what kind of install we're trying to do, create the key if it doesn't exist
if [ ! -f ~/.ssh/id_acadia ]; then
    # Create a dedicated ID for acadia operations that has no passphrase
    echo "Creating dedicated acadia SSH key..."
    ssh-keygen -Z aes128-ctr -f ~/.ssh/id_acadia -N ""
fi

# Deploy the key to the host if it's an initial install or we've never seen them
if $INITIAL || ! (ssh-keygen -F $IP > /dev/null) ; then
    deploy_ssh_key
fi

if $FIRMWARE; then
    # Retrieve the firmware
    echo "Retrieving firmware..."
    ftp -i -n $FIRMWARE_FTP_SERVER <<EOS
        user anonymous none
        cd firmware-latest
        get BOOT.BIN
        get image.ub
        get boot.scr
        bye
EOS

    if [ ! -f BOOT.BIN ] || [ ! -f image.ub ] || [ ! -f boot.scr ]; then
        echo "Failed to retrieve firmware files from the server."
        exit 1
    fi

    echo "Deploying firmware..."
    scp -i $HOME/.ssh/id_acadia ./{BOOT.BIN,image.ub,boot.scr} root@$IP:/run/media/mmcblk0p1
    rm ./{BOOT.BIN,image.ub,boot.scr}
    
    echo "Rebooting target..."
    ssh -i $HOME/.ssh/id_acadia root@$IP "reboot; exit"

    echo "Waiting for target availability..."
    sleep 100
    
    # The target rebooted, so we need to deploy the SSH key again
    deploy_ssh_key
fi

echo "Killing active screens..."
ssh -i $HOME/.ssh/id_acadia root@$IP killall screen

echo "Deploying acadia..."
scp -i $HOME/.ssh/id_acadia -q -r "$(dirname $SCRIPT)/../../acadia" root@$IP:/home/root

echo "Cleaning remote build files for acadia..."
ssh -i $HOME/.ssh/id_acadia root@$IP rm -r /home/root/acadia/pyacadia/{build,pyacadia.egg-info}

echo "Installing pyacadia..."
ssh -i $HOME/.ssh/id_acadia root@$IP pip3 install --force-reinstall acadia/pyacadia

if $INITIAL; then
    # scipy will be needed to import Acadia (waveforms uses get_window), so deploy that first
    echo "Deploying scipy..."
    wget https://files.pythonhosted.org/packages/c0/66/9cd4f501dd5ea03e4a4572ecd874936d0da296bd04d1c45ae1a4a75d9c3a/scipy-1.13.1-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl
    scp -i $HOME/.ssh/id_acadia scipy-1.13.1-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl root@$IP:/home/root
    echo "Installing scipy..."
    ssh -i $HOME/.ssh/id_acadia root@$IP "pip3 install scipy-1.13.1-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl; rm scipy-1.13.1-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
    rm scipy-1.13.1-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl

    echo "Configuring clocks and resetting RAM..."
    ssh -i $HOME/.ssh/id_acadia root@$IP 'python3 -c "from acadia import Acadia; a = Acadia(); a.attach(); a.configure_clocks(); a.reset_plddr0(); a.reset_plddr1(); a.reset_logic()"'

    # echo "Deploying LLVM..."
    # wget https://files.pythonhosted.org/packages/0a/e4/bce6de49651ade8b47ed7f0c11366d49be1bad752fbf16c1976545d389fa/llvmlite-0.42.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl
    # scp -i $HOME/.ssh/id_acadia llvmlite-0.42.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl root@$IP:/home/root/llvmlite-0.42.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl
    # echo "Installing LLVM..."
    # ssh -i $HOME/.ssh/id_acadia root@$IP "pip3 install llvmlite-0.42.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl; rm llvmlite-0.42.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
    # rm llvmlite-0.42.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl

    # echo "Deploying numba..."
    # wget https://github.com/numba/numba/archive/refs/tags/0.59.1.tar.gz
    # scp -i $HOME/.ssh/id_acadia -r 0.59.1.tar.gz root@$IP:/home/root
    # echo "Installing numba..."
    # ssh -i $HOME/.ssh/id_acadia root@$IP "tar -xzf 0.59.1.tar.gz; pip3 install ./numba-0.59.1; rm -r numba-0.59.1; rm 0.59.1.tar.gz"
    # rm 0.59.1.tar.gz
fi

echo "Complete."
