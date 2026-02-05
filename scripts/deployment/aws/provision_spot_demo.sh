#!/bin/bash
set -e

# Configuration
INSTANCE_TYPE="t3.medium"
REGION="us-east-1"
KEY_NAME="ml-pipeline-key" # Change this to your key name
AMI_ID="" # Will be fetched automatically
SG_NAME="ml-pipeline-sg"

# Disable AWS Pager to avoid issues in non-interactive shells
export AWS_PAGER=""

# Colors
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}Provisioning Zero-Cost Demo Instance...${NC}"

# Detect AWS CLI
if command -v aws &> /dev/null; then
    AWS_CMD="aws"
elif command -v aws.exe &> /dev/null; then
    AWS_CMD="aws.exe"
else
    echo "Error: AWS CLI not found. Please install it."
    exit 1
fi

# 1. Get latest Ubuntu 22.04 AMI
echo "Fetching latest Ubuntu 22.04 AMI..."
AMI_ID=$($AWS_CMD ec2 describe-images \
    --region $REGION \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" "Name=state,Values=available" \
    --query "sort_by(Images, &CreationDate)[-1].ImageId" \
    --output text | tr -d '\r')
echo "Using AMI: $AMI_ID"

# 2. Create Security Group
echo "Checking Security Group..."
if ! $AWS_CMD ec2 describe-security-groups --group-names $SG_NAME --region $REGION &>/dev/null; then
    echo "Creating Security Group $SG_NAME..."
    SG_ID=$($AWS_CMD ec2 create-security-group --group-name $SG_NAME --description "ML Pipeline Demo" --region $REGION --output text --query GroupId | tr -d '\r')
    
    # Allow SSH
    $AWS_CMD ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0 --region $REGION
    # Allow HTTP/HTTPS
    $AWS_CMD ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 80 --cidr 0.0.0.0/0 --region $REGION
    $AWS_CMD ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 443 --cidr 0.0.0.0/0 --region $REGION
    # Allow NodePorts (30000-32767)
    $AWS_CMD ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 30000-32767 --cidr 0.0.0.0/0 --region $REGION
    # Allow K8s API (6443)
    $AWS_CMD ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 6443 --cidr 0.0.0.0/0 --region $REGION
else
    SG_ID=$($AWS_CMD ec2 describe-security-groups --group-names $SG_NAME --region $REGION --query "SecurityGroups[0].GroupId" --output text | tr -d '\r')
    echo "Using existing Security Group: $SG_ID"
fi

# 3. Check Key Pair
if ! $AWS_CMD ec2 describe-key-pairs --key-names $KEY_NAME --region $REGION &>/dev/null; then
    echo "Creating Key Pair $KEY_NAME..."
    $AWS_CMD ec2 create-key-pair --key-name $KEY_NAME --region $REGION --query "KeyMaterial" --output text > ${KEY_NAME}.pem
    chmod 400 ${KEY_NAME}.pem
    echo "Key pair saved to ${KEY_NAME}.pem"
fi

# 4. Launch Spot Instance
echo "Launching Spot Instance ($INSTANCE_TYPE)..."

# Create config file for spot options to avoid quoting issues
cat <<EOF > spot-options.json
{
  "MarketType": "spot",
  "SpotOptions": {
    "SpotInstanceType": "one-time"
  }
}
EOF
# Create user-data script for Swap
cat <<EOF > user-data.sh
#!/bin/bash
# Create 2GB swap file
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
EOF

INSTANCE_ID=$($AWS_CMD ec2 run-instances \
    --image-id $AMI_ID \
    --count 1 \
    --instance-type $INSTANCE_TYPE \
    --key-name $KEY_NAME \
    --security-group-ids $SG_ID \
    --instance-market-options file://spot-options.json \
    --user-data file://user-data.sh \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=ml-pipeline-demo}]' \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
    --region $REGION \
    --query "Instances[0].InstanceId" \
    --output text | tr -d '\r')

rm spot-options.json
rm user-data.sh

echo "Instance launched: $INSTANCE_ID"
echo "Waiting for instance to be running..."
$AWS_CMD ec2 wait instance-running --instance-ids $INSTANCE_ID --region $REGION

PUBLIC_IP=$($AWS_CMD ec2 describe-instances --instance-ids $INSTANCE_ID --region $REGION --query "Reservations[0].Instances[0].PublicIpAddress" --output text | tr -d '\r')

echo -e "${GREEN}Instance Ready!${NC}"
echo "Public IP: $PUBLIC_IP"
echo ""
echo "To connect:"
echo "ssh -i ${KEY_NAME}.pem ubuntu@$PUBLIC_IP"
