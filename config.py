###
# Copyright (c) 2013, nicolas coevoet
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.conf as conf
import supybot.registry as registry

def configure(advanced):
    # This will be called by supybot to configure this module.  advanced is
    # a bool that specifies whether the user identified himself as an advanced
    # user or not.  You should effect your configuration by manipulating the
    # registry as appropriate.
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin('ChanTracker', True)


ChanTracker = conf.registerPlugin('ChanTracker')

conf.registerGlobalValue(ChanTracker, 'pool',
    registry.Integer(60, """delay between two check about mode removal, in seconds, note, it's also based on irc activity, so removal may be delayed a bit"""))

conf.registerGlobalValue(ChanTracker, 'modesToAsk',
    registry.CommaSeparatedListOfStrings("b,q", """sync lists for those modes"""))
    
conf.registerGlobalValue(ChanTracker, 'modesToAskWhenOpped',
    registry.CommaSeparatedListOfStrings("e,I", """sync lists for those modes when opped"""))

conf.registerGlobalValue(ChanTracker, 'CAPS',
    registry.CommaSeparatedListOfStrings("account-notify,extended-join", """CAP asked to ircd, to track gecos/username and account changes"""))

conf.registerGlobalValue(ChanTracker, 'logsSize',
    registry.PositiveInteger(60, """number of messages to keep, per nick - not per nick per channel"""))

conf.registerGlobalValue(ChanTracker, 'opCommand',
    registry.String("CS OP %s %s", """command used to ask op first parameter is the channel and second parameter is bot's nick"""))

# per channel settings

conf.registerChannelValue(ChanTracker, 'autoExpire',
    registry.Integer(-1, """-1 means disabled, otherwise it's in seconds"""))
    
conf.registerChannelValue(ChanTracker, 'logChannel',
    registry.String("", """where bot annonces op's actions"""))
    
conf.registerChannelValue(ChanTracker, 'keepOp',
    registry.Boolean(False, """bot stays opped"""))

# this feature may be removed in future release

conf.registerChannelValue(ChanTracker, 'kickMode',
    registry.CommaSeparatedListOfStrings("b", """bot will kick affected users when mode is triggered, use if with caution, and report any bugs related to affected users by a mode"""))
    
conf.registerChannelValue(ChanTracker, 'kickMessage',
    registry.String("You are banned from this channel", """bot kick reason"""))

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
