set -a
source ~/jarvis/.secrets
set +a

cd ~/jarvis-alpha
exec .venv/bin/python3.12 -m brain.agents.buddy_agent \
  >> ~/jarvis-alpha/logs/alpha_buddy.log 2>> ~/jarvis-alpha/logs/alpha_buddy_error.log
