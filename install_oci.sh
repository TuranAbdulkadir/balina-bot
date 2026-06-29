#!/bin/bash
curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh -o install.sh
bash install.sh --accept-all-defaults
mkdir -p ~/.oci
cat << 'EOF' > ~/.oci/config
[DEFAULT]
user=ocid1.user.oc1..aaaaaaaai4f4hxatemb2hgq7ljw6o36vcdbsgj5uie4w657e6tlbfxl5rtga
fingerprint=f9:87:50:4d:36:9f:4e:96:2b:03:d0:c1:d7:ee:7c:11
tenancy=ocid1.tenancy.oc1..aaaaaaaa6cpc6th6uhqxsqm6ycbd6ath3bjlon7b56mqdyer5lex3nets7ja
region=eu-frankfurt-1
key_file=/home/ubuntu/balina_bot/oracle.pem
EOF
~/bin/oci iam compartment list --all > /home/ubuntu/compartments.json
~/bin/oci network subnet list --compartment-id ocid1.tenancy.oc1..aaaaaaaa6cpc6th6uhqxsqm6ycbd6ath3bjlon7b56mqdyer5lex3nets7ja > /home/ubuntu/subnets.json
~/bin/oci compute image list --compartment-id ocid1.tenancy.oc1..aaaaaaaa6cpc6th6uhqxsqm6ycbd6ath3bjlon7b56mqdyer5lex3nets7ja --operating-system "Canonical Ubuntu" --operating-system-version "22.04" --shape "VM.Standard.A1.Flex" > /home/ubuntu/images.json
~/bin/oci iam availability-domain list --compartment-id ocid1.tenancy.oc1..aaaaaaaa6cpc6th6uhqxsqm6ycbd6ath3bjlon7b56mqdyer5lex3nets7ja > /home/ubuntu/ads.json
