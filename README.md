# scotustician

Activate a virtual environment i.e. in :
```
conda create --name scotustician
conda activate scotustician
```
Install AWS CLI v2:
```
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
```
## Set-up
```
pip install -r requirements.txt
mkdir data
mkdir data/case
mkdir data/oa
```
## Run
```
sh run.sh SCOTUSTICIAN_S3
```
