#!/bin/bash

echo "Drive mount directory:"
read SD_DIR

echo "Hostname:"
read HOSTNAME

echo "MAC:"
read MAC

# https://stackoverflow.com/questions/59895/how-do-i-get-the-directory-where-a-bash-script-is-located-from-within-the-script
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ACADIA_DIR=$SCRIPT_DIR/..

# Copy acadia to card
echo "Copying acadia..."
cp -r $ACADIA_DIR $SD_DIR

echo "Configuring autostart..."
cp $SD_DIR/acadia/petalinux/autostart.sh $SD_DIR/autostart.sh
sed -i -e "s/customhostname/$HOSTNAME/g" -e "s/custommac/$MAC/g" $SD_DIR/autostart.sh

