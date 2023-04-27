cd /home/discord-bot
echo "Pulling"
git pull
echo "Pulled info"

echo "Installing dependencies"
pip install -r /home/discord-bot/requirements.txt
echo "Dependancies installed"

python3 /home/discord-bot/main.py