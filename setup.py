import os
import sys

from supybot.setup import plugin_setup

# Workaround pip changing the name of the root directory
(parent, dir_) = os.path.split(os.path.dirname(__file__))
sys.path.insert(0, parent)
sys.modules["ChanTracker"] = __import__(dir_)

plugin_setup(
    'ChanTracker',
)
