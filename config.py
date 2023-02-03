###
# Copyright (c) 2013, Nicolas Coevoet
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

## global settings

conf.registerGlobalValue(ChanTracker, 'pool',
    registry.Integer(-1, """delay between two checks about mode removal, in seconds.
        Note, check is also based on irc activity, so removal may be delayed a bit, -1 to disable delay"""))

conf.registerGlobalValue(ChanTracker, 'logsSize',
    registry.PositiveInteger(1, """number of messages to keep in logs. Note, this is per nick - not per nick per channel"""))

conf.registerGlobalValue(ChanTracker, 'quietCommand',
    registry.String("PRIVMSG ChanServ :QUIET $channel $hostmask",
        """command issued to quiet a user; $channel and $hostmask will be replaced at runtime"""))

conf.registerGlobalValue(ChanTracker, 'unquietCommand',
    registry.String("PRIVMSG ChanServ :UNQUIET $channel $hostmask",
        """command issued to unquiet a user; $channel and $hostmask will be replaced at runtime"""))

conf.registerGlobalValue(ChanTracker, 'announceNagInterval',
    registry.Integer(-1, """interval between two checks about announceNagMode, this setting is global"""))

conf.registerGlobalValue(ChanTracker, 'resolveIp',
    registry.Boolean(True, """trying to resolve host's ip with socket, could add latency"""))

## per-channel settings

conf.registerChannelValue(ChanTracker, 'modeD',
    registry.String("", """special mode if you want to use some specific stuff;
        $hostmask (*!*@*), $klinemask (*@*), $host, $channel, $reason, $nick and $duration are available"""))

conf.registerChannelValue(ChanTracker, 'useAccountBanIfPossible',
    registry.Boolean(False, """bot will use account bans when user is identified, only works for b,q,e,I and m (chantracker.m)"""))

conf.registerChannelValue(ChanTracker, 'avoidOverlap',
    registry.Boolean(False, """avoid overlap between items, bot will try to use existing items against users, some limitations with extended bans"""))

conf.registerChannelValue(ChanTracker, 'useIpForGateway',
    registry.Boolean(False, """use *!*@*ip bans instead of *!ident@gateway/* when gateway cloak is found and ends with ip.*"""))

conf.registerChannelValue(ChanTracker, 'triggerOps',
    registry.Boolean(False, """!ops triggers a message in logChannel"""))

conf.registerChannelValue(ChanTracker, 'allowOpToConfig',
    registry.Boolean(False, """grant channel operators the ability to configure some ChanTracker protections for their channel"""))

conf.registerChannelValue(ChanTracker, 'ignoreVoicedUser',
    registry.Boolean(False, """exempt voiced users from channel protections"""))

conf.registerChannelValue(ChanTracker, 'opCommand',
    registry.String("PRIVMSG ChanServ :OP $channel $nick", """command used to obtain channel operator status"""), opSettable=False)

conf.registerChannelValue(ChanTracker, 'modesToAsk',
    registry.CommaSeparatedListOfStrings(['b', 'q'], """list of channel modes to sync into the bot's tracking database when it joins the channel"""))

conf.registerChannelValue(ChanTracker, 'modesToAskWhenOpped',
    registry.CommaSeparatedListOfStrings(['e', 'I'], """list of channel modes to sync into the bot's tracking database when it is opped"""))

conf.registerChannelValue(ChanTracker, 'ignoreOnAbuse',
    registry.Boolean(False, """adds abusers on ignore for the punishment period"""))

## related to ban tracking

conf.registerChannelValue(ChanTracker, 'autoExpire',
    registry.Integer(-1, """default expiration time for newly placed bans; -1 disables auto-expiration, otherwise it's in seconds"""))
conf.registerChannelValue(ChanTracker, 'autoRemoveUnregisteredQuiets',
    registry.Boolean(True, """auto remove from database unregistered quiets once expired -q $~a"""))
conf.registerChannelValue(ChanTracker, 'allowPublicInfo',
    registry.Boolean(False, """allow !info to be returned in where it was called if True"""))
    
conf.registerChannelValue(ChanTracker, 'removeAllBans',
    registry.Boolean(False, """prevent accidental removal of all bans"""))
conf.registerChannelValue(ChanTracker, 'removeAllQuiets',
    registry.Boolean(False, """prevent accidental removal of all quiets"""))
conf.registerChannelValue(ChanTracker, 'removeAllExempts',
    registry.Boolean(False, """prevent accidental removal of all exempts"""))
conf.registerChannelValue(ChanTracker, 'removeAllInvites',
    registry.Boolean(False, """prevent accidental removal of all invites"""))


## related to logChannel

conf.registerChannelValue(ChanTracker, 'logChannel',
    registry.String("", """where bot announces op actions; it is highly recommended to set an appropriate operators channel
        to receive the various useful messages, nick can be used"""), opSettable=False)

conf.registerChannelValue(ChanTracker, 'useSmartLog',
    registry.Boolean(True, """compress multiple announce messages at the same time into a single one"""))

conf.registerChannelValue(ChanTracker, 'useColorForAnnounces',
    registry.Boolean(False, """use colors for announce messages"""))

conf.registerChannelValue(ChanTracker, 'announceOthers',
    registry.Boolean(True, """forward messages from quieted/banned users to logChannel; used when bot stays opped and channel is +z (reduced moderation).
        messages from users flagged as bad, or when channel is under attack will not be forwarded"""))

conf.registerChannelValue(ChanTracker, 'announceModeMadeByIgnored',
    registry.Boolean(True, """announce channel modes made by ignored user"""))

conf.registerChannelValue(ChanTracker, 'announceWithNotice',
    registry.Boolean(False, """use NOTICE instead of PRIVMSG to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceModes',
    registry.CommaSeparatedListOfStrings(['b', 'q', 'e', 'I', 'r', 'l', 'k', 'n', 't', 'F', 'i', 't', 's', 'n', 'c', 'C'],
        """announce modes listed to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceModeSync',
    registry.Boolean(False, """announce to logChannel that synchronisation of channel modes to tracking database has completed"""))

conf.registerChannelValue(ChanTracker, 'announceKick',
    registry.Boolean(True, """announce kick, remove, kill and kline to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceTopic',
    registry.Boolean(True, """announce topic changes to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceEdit',
    registry.Boolean(True, """announce new expiries on items to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceMark',
    registry.Boolean(True, """announce new comments on items to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceInTimeEditAndMark',
    registry.Boolean(False, """announce new expiries and comments to logChannel when they are created by the do, q, b, e and i commands"""))

conf.registerChannelValue(ChanTracker, 'announceMassRemoval',
    registry.Boolean(False, """announce mass ban removals 'undo *', 'uq *', 'ub *' to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceBotEdit',
    registry.Boolean(False, """when banning based on a channel protection trigger (such as flood prevention), announce the item expiry to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceBotMark',
    registry.Boolean(False, """when banning based on a channel protection trigger (such as flood prevention), announce the item comment to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceNotice',
    registry.Boolean(True, """announce channel notices to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceCtcp',
    registry.Boolean(True, """announce channel ctcps to logChannel"""))

conf.registerChannelValue(ChanTracker, 'announceNagMode',
    registry.CommaSeparatedListOfStrings([], """bot will announce that channel has such mode at announceNagInterval"""))

conf.registerChannelValue(ChanTracker, 'announceRepeatPattern',
    registry.Boolean(True, """announce repeat pattern created to logChannel"""))


## other settings

conf.registerChannelValue(ChanTracker, 'doNothingAboutOwnOpStatus',
    registry.Boolean(True, """bot will never try to change its own op status"""))

conf.registerChannelValue(ChanTracker, 'keepOp',
    registry.Boolean(False, """bot stays opped"""))

conf.registerChannelValue(ChanTracker, 'kickMode',
    registry.CommaSeparatedListOfStrings(['b'], """bot will kick affected users when mode is triggered;
        use with caution, if an op bans *!*@*, bot will kick everyone on the channel - see kickMax"""))

conf.registerChannelValue(ChanTracker, 'kickOnMode',
    registry.Boolean(False, """if the bot is not the kickMode issuer, it will still kick; use with caution"""))

conf.registerChannelValue(ChanTracker, 'kickMax',
    registry.Integer(-1, """if > 0, disable kick if affected users > kickMax, avoid to clean up entire channel with ban like *!*@*"""))

conf.registerChannelValue(ChanTracker, 'kickMessage',
    registry.CommaSeparatedListOfStrings(["You are banned from this channel"], """bot kick reason"""))

conf.registerChannelValue(ChanTracker, 'discloseOperator',
    registry.Boolean(True, """reveals operator's nick on sockpuppet action via the bot !b, !q, !r, !k (via the kick reason or banMessage/quietMessage)"""))

conf.registerChannelValue(ChanTracker, 'banMessage',
    registry.String("You have been banned on $channel", """set empty if you don't want the bot to tell something to the user
        when they have been banned (by/via the bot); in any case, if channel is under attack, bot will not send message;
        if filled, the operator nick will be given for accountability if differing"""))

conf.registerChannelValue(ChanTracker, 'banNotice',
    registry.Boolean(True, """if False, private message is used, if banMessage is not empty"""))

conf.registerChannelValue(ChanTracker, 'quietMessage',
    registry.String("You have been quieted on $channel", """set empty if you don't want the bot to tell something to the user
        when they have been quieted (by/via the bot); in any case, if channel is under attack, bot will not send message;
        if filled, the operator nick will be given for accountability if differing"""))

conf.registerChannelValue(ChanTracker, 'quietNotice',
    registry.Boolean(True, """if False, private message is used, if quietMessage is not empty"""))

conf.registerChannelValue(ChanTracker, 'proxyMsgOnly',
    registry.Boolean(True, """only send message to user on operator action if it was proxied through the bot"""))

conf.registerChannelValue(ChanTracker, 'trackAffected',
    registry.Boolean(True, """bot tracks affected users by mode change; if you encounter too much lag or cpu usage, you could disable this feature,
        but bot will never kick again affected users or remove voice/op/exempt etc of affected users"""))

conf.registerChannelValue(ChanTracker, 'doActionAgainstAffected',
    registry.Boolean(True, """devoice, deop, dehalfop user affected by a mode change"""))

conf.registerChannelValue(ChanTracker, 'useChannelBansForPermanentBan',
    registry.Boolean(True, """when users join the channel, check if user matches a permanent ban set in Channel plugin"""))

conf.registerChannelValue(ChanTracker, 'addKickMessageInComment',
    registry.Boolean(False, """add kick message to mode comment in tracking database"""))

conf.registerChannelValue(ChanTracker, 'askOpAboutMode',
    registry.Boolean(False, """in a private message, ask the op who added a mode about the duration of the ban and a comment on why it was set"""))

conf.registerChannelValue(ChanTracker, 'checkEvade',
    registry.Boolean(True, """bot will apply same duration and mode as the evaded ban; currently only works when someone identifies to an account
        and the account is banned, or has ip computed"""))

conf.registerChannelValue(ChanTracker, 'useChanServForQuiets',
    registry.Boolean(False, """if bot is not opped, use network services for quiet/unquiets"""))


## related to channel protection

# clone detection

conf.registerChannelValue(ChanTracker, 'clonePermit',
    registry.Integer(-1, """number of clones allowed , -1 to disable"""))
conf.registerChannelValue(ChanTracker, 'cloneMode',
    registry.String('d', """mode used by the bot when clone detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'cloneDuration',
    registry.PositiveInteger(60, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'cloneComment',
    registry.String('clone detected', """comment added to tracking database, empty for no comment"""))


# flood detection

conf.registerChannelValue(ChanTracker, 'floodPermit',
    registry.Integer(-1, """number of messages allowed during floodLife, -1 to disable"""))
conf.registerChannelValue(ChanTracker, 'floodLife',
    registry.PositiveInteger(7, """duration in seconds before messages are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'floodMode',
    registry.String('q', """mode used by the bot when flood detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'floodDuration',
    registry.PositiveInteger(60, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'floodComment',
    registry.String('flood detected', """comment added to tracking database, empty for no comment"""))


# another flood queue, for user with throttled irc client, who paste long text

conf.registerChannelValue(ChanTracker, 'lowFloodPermit',
    registry.Integer(-1, """number of messages allowed during lowFloodLife, -1 to disable"""))
conf.registerChannelValue(ChanTracker, 'lowFloodLife',
    registry.PositiveInteger(13, """duration in seconds before messages are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'lowFloodMode',
    registry.String('q', """mode used by the bot when low flood detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'lowFloodDuration',
    registry.PositiveInteger(180, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'lowFloodComment',
    registry.String('low flood detected', """comment added to tracking database, empty for no comment"""))


# repeat detection

conf.registerChannelValue(ChanTracker, 'repeatPermit',
    registry.Integer(-1, """number of triggers allowed during repeatLife, -1 to disable"""))
conf.registerChannelValue(ChanTracker, 'repeatLife',
    registry.PositiveInteger(12, """duration in seconds before triggers are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'repeatMode',
    registry.String('q', """mode used by the bot when repeat detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'repeatDuration',
    registry.PositiveInteger(180, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'repeatComment',
    registry.String('repeat detected', """comment added to tracking database, empty for no comment"""))


# pattern repeat detection

conf.registerChannelValue(ChanTracker, 'repeatMinimum',
    registry.PositiveInteger(8, """minimum length of pattern candidates to detect repetitions"""))
conf.registerChannelValue(ChanTracker, 'repeatPercent',
    registry.Probability(0.85, """percent of similarity required between pattern candidates"""))
conf.registerChannelValue(ChanTracker, 'repeatCount',
    registry.PositiveInteger(5, """number of occurences of pattern candidates"""))
conf.registerChannelValue(ChanTracker, 'repeatPatternMinimum',
    registry.Integer(-1, """minimum length to create automated pattern; if found, triggers same punishment as repeatMode/repeatDuration, -1 to disable"""))
conf.registerChannelValue(ChanTracker, 'repeatPatternLife',
    registry.PositiveInteger(300, """duration in seconds before automated patterns are removed"""))

conf.registerChannelValue(ChanTracker, 'shareComputedPatternID',
    registry.Integer(-1, """share computed patterns across channels using the same ID, -1 to disable"""))


# YES IT'S ANNOYING

conf.registerChannelValue(ChanTracker, 'capPermit',
    registry.Integer(-1, """number of UPPERCASE messages allowed, -1 to disable; see capPercent for definition of an UPPERCASE message"""))
conf.registerChannelValue(ChanTracker, 'capLife',
    registry.PositiveInteger(30, """duration in seconds before messages are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'capPercent',
    registry.Probability(0.75, """percentage of uppercase chars in a message to trigger a cap count"""))
conf.registerChannelValue(ChanTracker, 'capMode',
    registry.String('q', """mode used by the bot when cap detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'capDuration',
    registry.PositiveInteger(180, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'capComment',
    registry.String('capslock detected', """comment added to tracking database, empty for no comment"""))


# hilights

conf.registerChannelValue(ChanTracker, 'hilightPermit',
    registry.Integer(-1, """number of nicks allowed per message, -1 to disable; note it doesn't care if it's the same nick"""))
conf.registerChannelValue(ChanTracker, 'hilightMode',
    registry.String('q', """mode used by the bot when hilight detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'hilightDuration',
    registry.PositiveInteger(180, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'hilightComment',
    registry.String('hilight detected', """comment added to tracking database, empty for no comment"""))


# notices

conf.registerChannelValue(ChanTracker, 'noticePermit',
    registry.Integer(-1, """number of messages allowed, -1 to disable, advice 0"""))
conf.registerChannelValue(ChanTracker, 'noticeLife',
    registry.PositiveInteger(3, """duration in seconds before messages are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'noticeMode',
    registry.String('q', """mode used by the bot when notice detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'noticeDuration',
    registry.PositiveInteger(300, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'noticeComment',
    registry.String('notice detected', """comment added to tracking database, empty for no comment"""))


# ctcps

conf.registerChannelValue(ChanTracker, 'ctcpPermit',
    registry.Integer(-1, """number of messages allowed, -1 to disable"""))
conf.registerChannelValue(ChanTracker, 'ctcpLife',
    registry.PositiveInteger(3, """duration in seconds before messages are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'ctcpMode',
    registry.String('b', """mode used by the bot when ctcp detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'ctcpDuration',
    registry.PositiveInteger(1800, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'ctcpComment',
    registry.String('ctcp detected', """comment added to tracking database, empty for no comment"""))


# join/part flood

conf.registerChannelValue(ChanTracker, 'cyclePermit',
    registry.Integer(-1, """number of cycles allowed, -1 to disable; counts parts and quits"""))
conf.registerChannelValue(ChanTracker, 'cycleLife',
    registry.PositiveInteger(180, """duration in seconds before cycles are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'cycleMode',
    registry.String('b', """mode used by the bot when cycle detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'cycleDuration',
    registry.PositiveInteger(1800, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'cycleComment',
    registry.String('cycle detected', """comment added to tracking database, empty for no comment"""))
conf.registerChannelValue(ChanTracker, 'cycleForward',
    registry.String('', """if your ircd supports that, you can forward the user to a specific channel"""))


# massjoin from a host

conf.registerChannelValue(ChanTracker, 'massJoinPermit',
    registry.Integer(-1, """number of joins allowed, -1 to disable, note, it could mixup a bit with cycle detection"""))
conf.registerChannelValue(ChanTracker, 'massJoinLife',
    registry.PositiveInteger(60, """duration in seconds before messages are removed from count"""))
conf.registerChannelValue(ChanTracker, 'massJoinMode',
    registry.String('+rq-z $~a', """mode used by the bot when massjoin detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'massJoinDuration',
    registry.PositiveInteger(300, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'massJoinUnMode',
    registry.String('-rq+z $~a', """mode used by the bot when massJoinDuration is finished"""))


# nick changes flood

conf.registerChannelValue(ChanTracker, 'nickPermit',
    registry.Integer(-1, """number of nick changes allowed, -1 to disable"""))
conf.registerChannelValue(ChanTracker, 'nickLife',
    registry.PositiveInteger(300, """duration in seconds before nick changes are removed from count"""))
conf.registerChannelValue(ChanTracker, 'nickMode',
    registry.String('q', """mode used by the bot when nick detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'nickDuration',
    registry.PositiveInteger(300, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'nickComment',
    registry.String('nick changes flood detected', """comment added to tracking database, empty for no comment"""))


# if you enable this, each time someone triggers other protection, it increases this counter

conf.registerChannelValue(ChanTracker, 'badPermit',
    registry.Integer(-1, """number of actions allowed, -1 to disable; each time bot had to act on a user, it increases this counter"""))
conf.registerChannelValue(ChanTracker, 'badLife',
    registry.PositiveInteger(600, """duration in seconds before actions are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'badMode',
    registry.String('b', """mode used by the bot when bad detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'badDuration',
    registry.PositiveInteger(86400, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'badComment',
    registry.String('bad detected', """comment added to tracking database, empty for no comment"""))


# if you enable this, each time someone triggers bad detection, it increases this counter

conf.registerChannelValue(ChanTracker, 'attackPermit',
    registry.Integer(-1, """number of bad actions allowed, -1 to disable; each time bot flags a user as bad, it increases this counter"""))
conf.registerChannelValue(ChanTracker, 'attackLife',
    registry.PositiveInteger(600, """duration in seconds before bad actions are removed from counter"""))
conf.registerChannelValue(ChanTracker, 'attackDuration',
    registry.PositiveInteger(1800, """punishment duration in seconds"""))
conf.registerChannelValue(ChanTracker, 'attackMode',
    registry.String('+rq-z $~a', """mode used by the bot when attack detection is triggered"""))
conf.registerChannelValue(ChanTracker, 'attackUnMode',
    registry.String('-rq+z $~a', """mode used by the bot when attackDuration is finished"""))


# netsplits

conf.registerChannelValue(ChanTracker, 'netsplitModes',
    registry.String('', """leave empty for no modes changes"""))
conf.registerChannelValue(ChanTracker, 'netsplitUnmodes',
    registry.String('', """leave empty for no modes changes"""))
conf.registerChannelValue(ChanTracker, 'netsplitDuration',
    registry.PositiveInteger(600, """duration of netsplit state when detected,
        it disables massjoin and cycle detection, and could set specific modes"""))
